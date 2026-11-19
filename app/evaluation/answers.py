"""Evaluate generated answers against the local golden set and access rules."""

import argparse
import json
import re
import unicodedata

from app.answers.generator import ABSTENTION, generate_answer
from app.db.connection import create_pool
from app.embeddings.client import OpenAIEmbedder
from app.retrieval.demo import DEMO_USERS
from app.retrieval.search import retrieve_chunks
from app.settings import get_settings
from app.evaluation.retrieval import load_cases, principal_for


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace(",", "")
    # Treat typographic ranges (5–7) like their written equivalent (5 to 7).
    text = re.sub(r"(?<=\d)\s*[–—-]\s*(?=\d)", " to ", text)
    text = re.sub(r"[^\w%]+", " ", text)
    # Gold phrases often use plural units while concise answers use a hyphenated
    # modifier (36 months vs. 36-month); compare those forms equivalently.
    text = re.sub(r"\b(month|day|week|year|hour|minute)s\b", r"\1", text)
    return text.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--ids", help="comma-separated golden case IDs; omit to evaluate all cases"
    )
    args = parser.parse_args()
    if not 1 <= args.top_k <= 20:
        parser.error("--top-k must be between 1 and 20")

    cases = load_cases()
    if args.ids:
        requested_ids = {item.strip() for item in args.ids.split(",") if item.strip()}
        known_ids = {case["id"] for case in cases}
        unknown_ids = requested_ids - known_ids
        if unknown_ids:
            parser.error(f"unknown case IDs: {', '.join(sorted(unknown_ids))}")
        cases = [case for case in cases if case["id"] in requested_ids]
    if not cases:
        parser.error("no evaluation cases selected")

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
    results = []
    try:
        for case, query_vector in zip(cases, query_vectors):
            principal = principal_for(case.get("user_groups", []))
            passages = retrieve_chunks(
                pool,
                organization_id=str(settings.rag_organization_id),
                user_id=DEMO_USERS[principal],
                question=case["question"],
                query_embedding=query_vector,
                top_k=args.top_k,
            )
            generation_error = None
            try:
                answer_result = generate_answer(settings, case["question"], passages)
            except RuntimeError as exc:
                # A malformed model answer should fail this case, not hide the
                # results for every later case in the selected batch.
                generation_error = str(exc)
                answer_result = {"answer": "", "sources": []}
            answer = answer_result["answer"]
            sources = answer_result["sources"]
            normalized_answer = normalize(answer)
            required = [normalize(term) for term in case.get("answer_must_contain", [])]
            content_ok = (
                answer == ABSTENTION if not case["answerable"]
                else bool(required) and all(term in normalized_answer for term in required)
            )
            cited_files = {source["filename"] for source in sources}
            relevant_files = set(case.get("relevant_docs") or [])
            forbidden_files = set(case.get("forbidden_docs") or [])
            source_ok = (
                not sources if not case["answerable"]
                else bool(sources) and bool(cited_files & relevant_files)
            )
            no_forbidden = not bool(cited_files & forbidden_files)
            results.append(
                {
                    "id": case["id"],
                    "type": case.get("type", "unspecified"),
                    "principal": principal,
                    "content_ok": content_ok,
                    "source_ok": source_ok,
                    "no_forbidden_source": no_forbidden,
                    "answer": answer,
                    "sources": sources,
                    **({"generation_error": generation_error} if generation_error else {}),
                }
            )
    finally:
        pool.close()

    passed = [
        item for item in results
        if item["content_ok"] and item["source_ok"] and item["no_forbidden_source"]
    ]
    print(json.dumps(
        {
            "mode": "answer evaluation; selected questions and retrieved passages sent to OpenAI",
            "cases": len(results),
            "passed": len(passed),
            "failed_ids": [item["id"] for item in results if item not in passed],
            "case_results": results,
        },
        indent=2,
        ensure_ascii=False,
    ))
    if len(passed) != len(results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
