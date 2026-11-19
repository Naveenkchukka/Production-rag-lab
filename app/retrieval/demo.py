"""Run a local retrieval query as one of the seeded demo principals."""

import argparse
import json

from app.db.connection import create_pool
from app.embeddings.client import OpenAIEmbedder
from app.retrieval.search import retrieve_chunks
from app.settings import get_settings


DEMO_USERS = {
    "public": "10000000-0000-4000-8000-000000000001",
    "employee": "10000000-0000-4000-8000-000000000002",
    "hr": "10000000-0000-4000-8000-000000000003",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal", choices=DEMO_USERS, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
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
        results = retrieve_chunks(
            pool,
            organization_id=str(settings.rag_organization_id),
            user_id=DEMO_USERS[args.principal],
            question=args.query,
            query_embedding=query_vector,
            top_k=args.top_k,
        )
    finally:
        pool.close()

    print(json.dumps({"principal": args.principal, "results": results}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
