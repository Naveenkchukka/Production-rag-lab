"""Measure retrieval hits and access-control leakage on the golden question set."""

import argparse
import json
from pathlib import Path

from app.db.connection import create_pool
from app.embeddings.client import OpenAIEmbedder
from app.retrieval.demo import DEMO_USERS
from app.retrieval.search import retrieve_chunks
from app.settings import get_settings


EVAL_PATH = Path(__file__).resolve().parents[2] / "data" / "course_corpus" / "eval" / "golden.jsonl"


def principal_for(groups: list[str]) -> str:
    memberships = set(groups)
    if "hr" in memberships:
        return "hr"
    if "employees" in memberships:
        return "employee"
    # The golden set omits group labels for general cases. The employee demo
    # principal can read public and employee material but not HR documents.
    return "employee"


def load_cases() -> list[dict]:
    cases = []
    for line_number, line in enumerate(EVAL_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        if not isinstance(case.get("question"), str) or not isinstance(case.get("id"), str):
            raise ValueError(f"Evaluation line {line_number} needs string id and question fields")
        if type(case.get("answerable")) is not bool:
            raise ValueError(f"Evaluation case {case['id']} needs a boolean answerable field")
        cases.append(case)
    if not cases:
        raise ValueError("Evaluation set is empty")
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.top_k <= 20:
        parser.error("--top-k must be between 1 and 20")

    cases = load_cases()
    settings = get_settings()
    embedder = OpenAIEmbedder(settings)
    try:
        query_vectors = embedder.embed([case["question"] for case in cases])
    finally:
        embedder.close()
    if len(query_vectors) != len(cases):
        raise RuntimeError("Embedding count did not match evaluation case count")

    pool = create_pool(settings)
    pool.open(wait=True, timeout=10)
    case_results = []
    try:
        for case, query_vector in zip(cases, query_vectors):
            principal = principal_for(case.get("user_groups", []))
            hits = retrieve_chunks(
                pool,
                organization_id=str(settings.rag_organization_id),
                user_id=DEMO_USERS[principal],
                question=case["question"],
                query_embedding=query_vector,
                top_k=args.top_k,
            )
            retrieved_docs = list(dict.fromkeys(result["filename"] for result in hits))
            relevant_docs = set(case.get("relevant_docs") or [])
            forbidden_docs = set(case.get("forbidden_docs") or [])
            hit_rank = next(
                (rank for rank, filename in enumerate(retrieved_docs, 1) if filename in relevant_docs),
                None,
            )
            forbidden_hit = bool(forbidden_docs.intersection(retrieved_docs))
            case_results.append(
                {
                    "id": case["id"],
                    "type": case.get("type", "unspecified"),
                    "answerable": case["answerable"],
                    "principal": principal,
                    "relevant_rank": hit_rank,
                    "forbidden_hit": forbidden_hit,
                }
            )
    finally:
        pool.close()

    answerable = [case for case in case_results if case["answerable"]]
    hits = [case for case in answerable if case["relevant_rank"] is not None]
    mrr = (
        sum(1 / case["relevant_rank"] for case in hits) / len(answerable)
        if answerable else 0.0
    )
    forbidden_leaks = [case["id"] for case in case_results if case["forbidden_hit"]]
    summary = {
        "mode": "retrieval-only; no passages sent to the answer model",
        "cases": len(case_results),
        "top_k": args.top_k,
        "answerable_cases": len(answerable),
        "hit_at_k": round(len(hits) / len(answerable), 4) if answerable else 0.0,
        "mean_reciprocal_rank": round(mrr, 4),
        "missed_answerable_ids": [case["id"] for case in answerable if case["relevant_rank"] is None],
        "forbidden_document_leak_ids": forbidden_leaks,
        "case_results": case_results,
    }
    print(json.dumps(summary, indent=2))
    if forbidden_leaks:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
