"""Preview chunk counts for documents admitted by the current policy."""

import re

from app.ingestion.chunking import CHUNKING_VERSION, MAX_CHUNK_TOKENS, OVERLAP_TOKENS, chunk_text
from app.ingestion.extract_preview import extract_text
from app.ingestion.inventory import RAW_DIR, inventory_documents, load_metadata
from app.ingestion.policy_preview import admission_reason


def main() -> None:
    documents = inventory_documents(load_metadata())
    total_chunks = 0
    total_tokens = 0
    print("Local chunk preview (counts only; no database writes or model calls)")
    print(f"Algorithm: {CHUNKING_VERSION}; max tokens={MAX_CHUNK_TOKENS}; overlap={OVERLAP_TOKENS}")
    for document in documents:
        if admission_reason(document["metadata"]):
            continue
        text, _ = extract_text(RAW_DIR / document["name"], document["suffix"])
        chunks = chunk_text(text)
        counts = [tokens for _, tokens in chunks]
        punctuation_starts = sum(bool(re.match(r"^[.,;:!?)]", content.lstrip())) for content, _ in chunks)
        very_short = sum(tokens < 20 for tokens in counts)
        total_chunks += len(chunks)
        total_tokens += sum(counts)
        print(
            f"{document['name']}: chunks={len(chunks)}, "
            f"tokens[min/avg/max]={min(counts) if counts else 0}/"
            f"{sum(counts) // len(counts) if counts else 0}/"
            f"{max(counts) if counts else 0}; "
            f"boundary warnings={punctuation_starts} punctuation-start, {very_short} under-20-token"
        )
    print(f"Total: {total_chunks} chunks; {total_tokens} tokens including overlap")


if __name__ == "__main__":
    main()
