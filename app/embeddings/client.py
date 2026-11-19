"""Bounded, token-checked client for OpenAI's embeddings API."""

import math

from openai import OpenAI
import tiktoken

from app.settings import Settings


MAX_INPUT_TOKENS = 8192
MAX_BATCH_ITEMS = 64
MAX_BATCH_TOKENS = 50_000


class OpenAIEmbedder:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.rag_embedding_model
        self.dimensions = settings.rag_embedding_dimensions
        self._encoding = tiktoken.encoding_for_model(self.model)
        self._client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=30.0,
            max_retries=2,
        )

    def close(self) -> None:
        self._client.close()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        token_counts = [len(self._encoding.encode(text)) for text in texts]
        if any(not text.strip() for text in texts):
            raise ValueError("Embedding inputs must not be empty")
        if any(count > MAX_INPUT_TOKENS for count in token_counts):
            raise ValueError(f"An embedding input exceeds {MAX_INPUT_TOKENS} tokens")

        vectors: list[list[float]] = []
        start = 0
        while start < len(texts):
            end = start
            batch_tokens = 0
            while end < len(texts) and end - start < MAX_BATCH_ITEMS:
                next_count = token_counts[end]
                if end > start and batch_tokens + next_count > MAX_BATCH_TOKENS:
                    break
                batch_tokens += next_count
                end += 1

            response = self._client.embeddings.create(
                model=self.model,
                input=texts[start:end],
                dimensions=self.dimensions,
                encoding_format="float",
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != end - start:
                raise RuntimeError("Embedding API returned an unexpected number of vectors")
            for item in ordered:
                vector = item.embedding
                if len(vector) != self.dimensions:
                    raise RuntimeError(
                        f"Embedding dimension mismatch: expected {self.dimensions}, received {len(vector)}"
                    )
                if not all(math.isfinite(value) for value in vector):
                    raise RuntimeError("Embedding API returned a non-finite vector value")
                vectors.append(vector)
            start = end
        return vectors
