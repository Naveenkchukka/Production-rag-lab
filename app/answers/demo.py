"""Run one local, access-controlled RAG question and answer."""

import argparse
import json

from app.answers.generator import generate_answer
from app.db.connection import create_pool
from app.embeddings.client import OpenAIEmbedder
from app.retrieval.demo import DEMO_USERS
from app.retrieval.search import retrieve_chunks
from app.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal", choices=DEMO_USERS, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    settings = get_settings()
    embedder = OpenAIEmbedder(settings)
    try:
        query_vector = embedder.embed([args.query])[0]
    finally:
        embedder.close()

    pool = create_pool(settings)
    pool.open(wait=True, timeout=10)
    try:
        passages = retrieve_chunks(
            pool,
            organization_id=str(settings.rag_organization_id),
            user_id=DEMO_USERS[args.principal],
            question=args.query,
            query_embedding=query_vector,
            top_k=args.top_k,
        )
    finally:
        pool.close()

    result = generate_answer(settings, args.query, passages)
    print(
        json.dumps(
            {"principal": args.principal, **result},
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
