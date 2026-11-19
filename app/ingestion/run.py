"""Prepare and, when explicitly requested, index the admitted local corpus."""

import argparse
import hashlib
import mimetypes
from pathlib import Path
import sys
import uuid

from psycopg.types.json import Jsonb

from app.db.connection import create_pool
from app.embeddings.client import OpenAIEmbedder
from app.ingestion.chunking import CHUNKING_VERSION, chunk_text
from app.ingestion.extract_preview import extract_text
from app.ingestion.inventory import RAW_DIR, inventory_documents, load_metadata
from app.ingestion.policy_preview import admission_reason
from app.settings import get_settings


class _RollbackIndexTransaction(Exception):
    """Roll back an otherwise successful database-only preflight."""


def prepare_documents() -> list[dict]:
    prepared = []
    for source in inventory_documents(load_metadata()):
        metadata = source["metadata"]
        if admission_reason(metadata):
            continue
        path = RAW_DIR / source["name"]
        extracted_text, _ = extract_text(path, source["suffix"])
        chunks = chunk_text(extracted_text)
        if not chunks:
            raise ValueError(f"No text chunks were extracted from {source['name']}")
        prepared.append(
            {
                "name": source["name"],
                "path": path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "byte_size": path.stat().st_size,
                "content_type": mimetypes.guess_type(source["name"])[0] or "application/octet-stream",
                "metadata": metadata,
                "chunks": chunks,
            }
        )
    return prepared


def store_index(
    settings,
    documents: list[dict],
    vectors: list[list[float]],
    *,
    rollback_on_success: bool = False,
) -> tuple[int, int]:
    expected_vectors = sum(len(document["chunks"]) for document in documents)
    if len(vectors) != expected_vectors:
        raise ValueError(f"Expected {expected_vectors} vectors, received {len(vectors)}")

    pool = create_pool(settings)
    pool.open(wait=True, timeout=10)
    stage = "opening database transaction"
    stored_chunks = 0
    try:
        with pool.connection() as connection:
            with connection.transaction():
                stage = "setting tenant and worker context"
                connection.execute(
                    "SELECT set_config('rag.organization_id', %s, true)",
                    (str(settings.rag_organization_id),),
                )
                connection.execute(
                    "SELECT set_config('rag.user_id', %s, true)",
                    (str(settings.rag_ingestor_user_id),),
                )

                cursor = 0
                for document in documents:
                    version = str(document["metadata"]["version"])
                    document_id = uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"harbordesk:{settings.rag_organization_id}:{document['sha256']}:{version}",
                    )
                    existing = connection.execute(
                        "SELECT id FROM rag.documents "
                        "WHERE organization_id = %s AND sha256 = %s AND version = %s",
                        (settings.rag_organization_id, document["sha256"], version),
                    ).fetchone()
                    document_values = (
                        document["name"], document["content_type"], document["byte_size"],
                        document["metadata"]["trust"],
                        document["metadata"].get("contains_pii", False),
                        Jsonb(document["metadata"]),
                    )
                    if existing:
                        document_id = existing[0]
                        stage = f"updating existing document row for {document['name']}"
                        connection.execute(
                            """
                            UPDATE rag.documents
                            SET filename = %s, content_type = %s, byte_size = %s,
                                status = 'processing', trust = %s, contains_pii = %s,
                                metadata = %s, updated_at = now()
                            WHERE organization_id = %s AND id = %s
                            """,
                            (*document_values, settings.rag_organization_id, document_id),
                        )
                    else:
                        stage = f"inserting document row for {document['name']}"
                        connection.execute(
                            """
                            INSERT INTO rag.documents
                                (id, organization_id, filename, sha256, version, content_type,
                                 byte_size, status, trust, contains_pii, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'processing', %s, %s, %s)
                            """,
                            (
                                document_id, settings.rag_organization_id, document["name"],
                                document["sha256"], version, document["content_type"],
                                document["byte_size"], document["metadata"]["trust"],
                                document["metadata"].get("contains_pii", False),
                                Jsonb(document["metadata"]),
                            ),
                        )

                    stage = f"loading access groups for {document['name']}"
                    access_names = document["metadata"]["access"]
                    group_rows = connection.execute(
                        "SELECT id, name FROM rag.access_groups "
                        "WHERE organization_id = %s AND name = ANY(%s)",
                        (settings.rag_organization_id, access_names),
                    ).fetchall()
                    group_ids = {name: group_id for group_id, name in group_rows}
                    if set(group_ids) != set(access_names):
                        raise ValueError(f"Seeded access groups are missing for {document['name']}")

                    stage = f"writing access mappings for {document['name']}"
                    connection.execute(
                        "DELETE FROM rag.document_access_groups "
                        "WHERE organization_id = %s AND document_id = %s",
                        (settings.rag_organization_id, document_id),
                    )
                    with connection.cursor() as db_cursor:
                        db_cursor.executemany(
                            "INSERT INTO rag.document_access_groups "
                            "(organization_id, document_id, group_id) VALUES (%s, %s, %s)",
                            [
                                (settings.rag_organization_id, document_id, group_ids[name])
                                for name in access_names
                            ],
                        )

                    stage = f"replacing chunks for {document['name']}"
                    connection.execute(
                        "DELETE FROM rag.document_chunks "
                        "WHERE organization_id = %s AND document_id = %s",
                        (settings.rag_organization_id, document_id),
                    )
                    chunk_rows = []
                    for chunk_index, (content, _token_count) in enumerate(document["chunks"]):
                        vector = vectors[cursor]
                        cursor += 1
                        vector_literal = "[" + ",".join(format(value, ".9g") for value in vector) + "]"
                        chunk_rows.append(
                            (
                                uuid.uuid4(), settings.rag_organization_id, document_id,
                                document["sha256"], chunk_index, CHUNKING_VERSION, content,
                                Jsonb({"chunk_index": chunk_index}), settings.rag_embedding_model,
                                vector_literal,
                            )
                        )
                    with connection.cursor() as db_cursor:
                        db_cursor.executemany(
                            """
                            INSERT INTO rag.document_chunks
                                (id, organization_id, document_id, source_sha256, chunk_index,
                                 chunking_version, content, source_locator, embedding_model, embedding)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                            """,
                            chunk_rows,
                        )
                    stage = f"marking {document['name']} indexed"
                    final_status = (
                        "archived" if document["metadata"]["status"] == "archived" else "indexed"
                    )
                    connection.execute(
                        "UPDATE rag.documents SET status = %s, updated_at = now() "
                        "WHERE organization_id = %s AND id = %s",
                        (final_status, settings.rag_organization_id, document_id),
                    )
                    stored_chunks += len(chunk_rows)

                stage = "checking post-write visibility"
                visible = connection.execute(
                    """
                    SELECT count(DISTINCT d.id), count(c.id)
                    FROM rag.documents d
                    LEFT JOIN rag.document_chunks c
                      ON c.organization_id = d.organization_id AND c.document_id = d.id
                    WHERE d.organization_id = %s AND d.status IN ('indexed', 'archived')
                      AND d.filename = ANY(%s)
                    """,
                    (settings.rag_organization_id, [doc["name"] for doc in documents]),
                ).fetchone()
                if visible != (len(documents), stored_chunks):
                    raise RuntimeError(f"Post-write visibility check failed: {visible}")
                if rollback_on_success:
                    raise _RollbackIndexTransaction()
        return len(documents), stored_chunks
    except _RollbackIndexTransaction:
        return len(documents), stored_chunks
    except Exception as exc:
        raise RuntimeError(f"Database stage '{stage}' failed: {type(exc).__name__}: {exc}") from exc
    finally:
        pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute", action="store_true",
        help="send admitted chunk text to OpenAI and write the index to Postgres",
    )
    mode.add_argument(
        "--db-only-preflight", action="store_true",
        help="exercise the full database write path with zero vectors, then roll it back",
    )
    args = parser.parse_args()

    try:
        documents = prepare_documents()
        chunk_count = sum(len(document["chunks"]) for document in documents)
        token_count = sum(
            tokens for document in documents for _, tokens in document["chunks"]
        )
        print("Ingestion plan (document text remains local until --execute)")
        print(f"Documents: {len(documents)}; chunks: {chunk_count}; tokens including overlap: {token_count}")
        archived_count = sum(doc["metadata"]["status"] == "archived" for doc in documents)
        print(f"Archived documents retained for historical queries: {archived_count}")
        print("Excluded by policy: untrusted and PII-marked documents")
        if args.db_only_preflight:
            settings = get_settings()
            zero_vectors = [[0.0] * settings.rag_embedding_dimensions for _ in range(chunk_count)]
            store_index(settings, documents, zero_vectors, rollback_on_success=True)
            print("Database-only preflight passed; temporary rows were rolled back. No OpenAI request was made.")
            return
        if not args.execute:
            print("Dry run only. No OpenAI request and no database write was made.")
            print("Review this plan before running again with --execute.")
            return

        settings = get_settings()
        texts = [content for document in documents for content, _ in document["chunks"]]
        embedder = OpenAIEmbedder(settings)
        try:
            vectors = embedder.embed(texts)
        finally:
            embedder.close()
        indexed_documents, indexed_chunks = store_index(settings, documents, vectors)
        archived_count = sum(doc["metadata"]["status"] == "archived" for doc in documents)
        print(
            f"Stored {indexed_documents} documents ({indexed_documents - archived_count} current, "
            f"{archived_count} archived) and {indexed_chunks} chunks; "
            f"model={settings.rag_embedding_model}; dimensions={settings.rag_embedding_dimensions}."
        )
    except Exception as exc:
        print(f"Ingestion stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
