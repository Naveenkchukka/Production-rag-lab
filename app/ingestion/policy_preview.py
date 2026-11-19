"""Preview the first-index admission policy using metadata only."""

from collections import Counter

from app.ingestion.inventory import inventory_documents, load_metadata


def admission_reason(metadata: dict) -> str | None:
    """Return why a file is excluded, or None if it can enter the first index."""
    if metadata.get("trust") != "trusted":
        return "document is marked untrusted"
    if metadata.get("contains_pii", False):
        return "document is marked as containing PII"
    return None


def main() -> None:
    documents = inventory_documents(load_metadata())
    included = 0
    skipped_reasons: Counter[str] = Counter()
    groups: Counter[str] = Counter()
    print("First-index admission preview (metadata only; no text is processed)")
    for document in documents:
        metadata = document["metadata"]
        reason = admission_reason(metadata)
        if reason:
            skipped_reasons[reason] += 1
            print(f"SKIP    {document['name']}: {reason}")
            continue
        included += 1
        groups.update(metadata["access"])
        archive_note = ", historical only" if metadata["status"] == "archived" else ""
        print(
            f"INCLUDE {document['name']}: groups={','.join(metadata['access'])}; "
            f"status={metadata['status']}{archive_note}"
        )
    print(f"\nIncluded: {included}; skipped: {sum(skipped_reasons.values())}")
    print(f"Included document group counts: {dict(sorted(groups.items()))}")
    print(f"Skip reasons: {dict(sorted(skipped_reasons.items()))}")


if __name__ == "__main__":
    main()
