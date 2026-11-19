"""Hybrid vector and keyword retrieval with tenant/user RLS context."""

import re

from psycopg_pool import ConnectionPool


_ENGLISH_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "did",
    "do", "does", "for", "from", "how", "i", "in", "is", "it", "me", "my",
    "of", "on", "or", "our", "please", "should", "tell", "that", "the", "their",
    "them", "there", "this", "to", "us", "was", "what", "when", "where", "which",
    "who", "why", "will", "with", "would", "you", "your",
}
_ARCHIVE_CUE = re.compile(r"\b(?:old|previous|prior|historical|archived|before)\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

SEARCH_SQL = """
WITH search_input AS (
    SELECT %s::vector AS embedding,
           websearch_to_tsquery('simple', %s) AS tsq,
           %s::boolean AS allow_archived,
           %s::text[] AS requested_versions
),
vector_results AS (
    SELECT c.id, c.document_id, d.filename, d.version, d.status, c.content, c.source_locator,
           row_number() OVER (ORDER BY c.embedding <=> si.embedding) AS result_rank
    FROM rag.document_chunks c
    JOIN rag.documents d
      ON d.organization_id = c.organization_id AND d.id = c.document_id
    CROSS JOIN search_input si
    WHERE d.trust = 'trusted' AND d.contains_pii = false
      AND (
          d.status = 'indexed'
          OR (d.status = 'archived' AND si.allow_archived
              AND (cardinality(si.requested_versions) = 0
                   OR d.version = ANY(si.requested_versions)))
      )
    ORDER BY c.embedding <=> si.embedding
    LIMIT %s
),
keyword_results AS (
    SELECT c.id, c.document_id, d.filename, d.version, d.status, c.content, c.source_locator,
           row_number() OVER (ORDER BY ts_rank_cd(c.search_text, si.tsq) DESC) AS result_rank
    FROM rag.document_chunks c
    JOIN rag.documents d
      ON d.organization_id = c.organization_id AND d.id = c.document_id
    CROSS JOIN search_input si
    WHERE d.trust = 'trusted' AND d.contains_pii = false
      AND (
          d.status = 'indexed'
          OR (d.status = 'archived' AND si.allow_archived
              AND (cardinality(si.requested_versions) = 0
                   OR d.version = ANY(si.requested_versions)))
      )
      AND c.search_text @@ si.tsq
    ORDER BY ts_rank_cd(c.search_text, si.tsq) DESC
    LIMIT %s
),
ranked_candidates AS (
    SELECT id, document_id, filename, version, status, content, source_locator,
           1.0 / (60 + result_rank) AS rrf_score
    FROM vector_results
    UNION ALL
    SELECT id, document_id, filename, version, status, content, source_locator,
           1.0 / (60 + result_rank) AS rrf_score
    FROM keyword_results
)
SELECT id, document_id, filename, version, status, content, source_locator,
       sum(rrf_score) AS score
FROM ranked_candidates
GROUP BY id, document_id, filename, version, status, content, source_locator
ORDER BY score DESC
LIMIT %s
"""


def retrieve_chunks(
    pool: ConnectionPool,
    *,
    organization_id: str,
    user_id: str,
    question: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    if not question.strip():
        raise ValueError("Question must not be empty")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")

    vector = "[" + ",".join(format(value, ".9g") for value in query_embedding) + "]"
    terms = re.findall(r"[^\W_]+", question.casefold())
    meaningful_terms = [term for term in terms if term not in _ENGLISH_STOP_WORDS]
    lexical_query = " OR ".join(meaningful_terms or terms)
    requested_versions = _YEAR.findall(question)
    allow_archived = bool(requested_versions or _ARCHIVE_CUE.search(question))
    candidate_limit = top_k * 4
    with pool.connection() as connection:
        with connection.transaction():
            connection.execute(
                "SELECT set_config('rag.organization_id', %s, true)", (organization_id,)
            )
            connection.execute(
                "SELECT set_config('rag.user_id', %s, true)", (user_id,)
            )
            rows = connection.execute(
                SEARCH_SQL,
                (
                    vector, lexical_query, allow_archived, requested_versions,
                    candidate_limit, candidate_limit, top_k,
                ),
            ).fetchall()
    return [
        {
            "chunk_id": str(row[0]),
            "document_id": str(row[1]),
            "filename": row[2],
            "version": row[3],
            "status": row[4],
            "content": row[5],
            "source_locator": row[6],
            "score": float(row[7]),
        }
        for row in rows
    ]
