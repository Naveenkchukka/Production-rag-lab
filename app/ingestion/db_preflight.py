"""Exercise document and chunk writes through the app role, then roll back."""

import sys
import uuid

from app.db.connection import create_pool
from app.settings import get_settings


class _RollbackPreflight(Exception):
    """Force a successful preflight transaction to roll back cleanly."""


def main() -> None:
    settings = get_settings()
    pool = create_pool(settings)
    pool.open(wait=True, timeout=10)
    try:
        try:
            with pool.connection() as connection:
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('rag.organization_id', %s, true)",
                        (str(settings.rag_organization_id),),
                    )
                    connection.execute(
                        "SELECT set_config('rag.user_id', %s, true)",
                        (str(settings.rag_ingestor_user_id),),
                    )
                    context = connection.execute(
                        "SELECT current_user, current_setting('rag.organization_id', true), "
                        "current_setting('rag.user_id', true)"
                    ).fetchone()
                    expected_context = (
                        settings.rag_db_user,
                        str(settings.rag_organization_id),
                        str(settings.rag_ingestor_user_id),
                    )
                    print(f"App database context: {context}")
                    if context != expected_context:
                        raise RuntimeError(f"App database context mismatch: expected {expected_context}")

                    organization_id = settings.rag_organization_id
                    document_id = uuid.UUID("90000000-0000-4000-8000-000000000001")
                    chunk_id = uuid.UUID("90000000-0000-4000-8000-000000000002")
                    source_hash = "e" * 64
                    connection.execute(
                        """
                        INSERT INTO rag.documents
                            (id, organization_id, filename, sha256, version, content_type,
                             byte_size, status, trust, contains_pii, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            document_id, organization_id, "synthetic-preflight.md", source_hash,
                            "preflight", "text/markdown", 1, "processing", "trusted", False,
                            '{"preflight":true}',
                        ),
                    )
                    public_group = connection.execute(
                        "SELECT id FROM rag.access_groups WHERE organization_id = %s AND name = 'public'",
                        (organization_id,),
                    ).fetchone()
                    if public_group is None:
                        raise RuntimeError("Seeded public access group is missing")
                    connection.execute(
                        "INSERT INTO rag.document_access_groups "
                        "(organization_id, document_id, group_id) VALUES (%s, %s, %s)",
                        (organization_id, document_id, public_group[0]),
                    )
                    connection.execute(
                        """
                        INSERT INTO rag.document_chunks
                            (id, organization_id, document_id, source_sha256, chunk_index,
                             chunking_version, content, embedding_model, embedding)
                        VALUES (%s, %s, %s, %s, 0, 'preflight', 'synthetic preflight only',
                                'preflight', array_fill(0::real, ARRAY[512])::vector)
                        """,
                        (chunk_id, organization_id, document_id, source_hash),
                    )
                    visible = connection.execute(
                        """
                        SELECT d.filename, count(c.id)
                        FROM rag.documents d
                        LEFT JOIN rag.document_chunks c
                          ON c.organization_id = d.organization_id AND c.document_id = d.id
                        WHERE d.id = %s
                        GROUP BY d.filename
                        """,
                        (document_id,),
                    ).fetchone()
                    if visible != ("synthetic-preflight.md", 1):
                        raise RuntimeError(f"RLS visibility check failed: {visible}")
                    print("Synthetic document and chunk are writable and visible through the app role.")
                    raise _RollbackPreflight()
        except _RollbackPreflight:
            print("Preflight transaction rolled back; no rows were retained.")
    finally:
        pool.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Database preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
