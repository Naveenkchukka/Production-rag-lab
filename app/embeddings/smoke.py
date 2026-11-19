"""Verify OpenAI embedding configuration using synthetic text only."""

from app.embeddings.client import OpenAIEmbedder
from app.settings import get_settings


def main() -> None:
    settings = get_settings()
    embedder = OpenAIEmbedder(settings)
    try:
        vectors = embedder.embed(["Synthetic embedding connection check; no corpus text."])
    finally:
        embedder.close()
    print(
        "OpenAI embeddings API is ready; "
        f"model={settings.rag_embedding_model}; dimensions={len(vectors[0])}; "
        "input=synthetic only"
    )


if __name__ == "__main__":
    main()
