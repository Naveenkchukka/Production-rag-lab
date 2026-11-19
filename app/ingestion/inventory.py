"""Validate the supplied course corpus manifest without reading file contents."""

from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "course_corpus" / "raw"
METADATA_PATH = RAW_DIR / "_metadata.json"
EVAL_PATH = ROOT / "data" / "course_corpus" / "eval" / "golden.jsonl"
SUPPORTED_SUFFIXES = {".csv", ".html", ".md", ".pdf", ".txt"}
ACCESS_GROUPS = {"public", "employees", "hr"}
REQUIRED_METADATA = {
    "title", "department", "doc_type", "access", "version", "status", "trust", "language"
}


class InventoryError(Exception):
    pass


def validate_filename(name: object) -> str:
    if not isinstance(name, str) or not name or name in {".", ".."}:
        raise InventoryError(f"Invalid source filename: {name!r}")
    if "/" in name or "\\" in name:
        raise InventoryError(f"Manifest entry must be a filename, not a path: {name!r}")
    return name


def load_metadata() -> dict:
    try:
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InventoryError(f"Cannot read corpus metadata: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InventoryError(f"Corpus metadata is not valid JSON: {exc}") from exc
    if not isinstance(metadata, dict):
        raise InventoryError("Corpus metadata root must be a JSON object")
    return metadata


def inventory_documents(metadata: dict) -> list[dict]:
    if not RAW_DIR.is_dir():
        raise InventoryError(f"Source directory is missing: {RAW_DIR}")
    entries = {name for name in metadata if name != "_about"}
    if not entries:
        raise InventoryError("Corpus metadata contains no document entries")

    disk_files = {path.name for path in RAW_DIR.iterdir() if path.is_file() and path.name != "_metadata.json"}
    errors = []
    for name in sorted(disk_files - entries):
        errors.append(f"Source file has no metadata entry: {name}")
    for name in sorted(entries - disk_files):
        errors.append(f"Metadata entry has no source file: {name}")

    documents = []
    for raw_name in sorted(entries & disk_files):
        try:
            name = validate_filename(raw_name)
        except InventoryError as exc:
            errors.append(str(exc))
            continue
        item = metadata[raw_name]
        if not isinstance(item, dict):
            errors.append(f"Metadata for {name} must be an object")
            continue
        missing = REQUIRED_METADATA - set(item)
        if missing:
            errors.append(f"{name} is missing metadata fields: {', '.join(sorted(missing))}")
            continue
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            errors.append(f"Unsupported source format for {name}: {suffix or '(none)'}")
        access = item.get("access")
        if (not isinstance(access, list) or not access
                or any(group not in ACCESS_GROUPS for group in access)):
            errors.append(f"{name} has invalid access groups; expected values from {sorted(ACCESS_GROUPS)}")
        if item.get("status") not in {"active", "archived"}:
            errors.append(f"{name} has an invalid document status")
        if item.get("trust") not in {"trusted", "untrusted"}:
            errors.append(f"{name} has an invalid trust label")
        pii = item.get("contains_pii", False)
        if type(pii) is not bool:
            errors.append(f"{name} contains_pii must be true or false")
        try:
            size = (RAW_DIR / name).stat().st_size
        except OSError as exc:
            errors.append(f"Cannot stat source file {name}: {exc}")
            continue
        if size == 0:
            errors.append(f"Source file is empty: {name}")
        documents.append({"name": name, "suffix": suffix, "size": size, "metadata": item})

    if errors:
        raise InventoryError("\n- " + "\n- ".join(errors))
    return documents


def inventory_questions(metadata: dict) -> list[dict]:
    questions = []
    seen_ids = set()
    try:
        lines = EVAL_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InventoryError(f"Cannot read evaluation set: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InventoryError(f"Invalid evaluation JSON on line {line_number}: {exc}") from exc
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise InventoryError(f"Evaluation line {line_number} needs a string id")
        if case["id"] in seen_ids:
            raise InventoryError(f"Duplicate evaluation id: {case['id']}")
        seen_ids.add(case["id"])
        if type(case.get("answerable")) is not bool:
            raise InventoryError(f"Evaluation case {case['id']} needs a boolean answerable field")
        for field in ("relevant_docs", "forbidden_docs"):
            names = case.get(field, [])
            if not isinstance(names, list):
                raise InventoryError(f"Evaluation field {field} must be a list in {case['id']}")
            for raw_name in names:
                name = validate_filename(raw_name)
                if name not in metadata:
                    raise InventoryError(f"Unknown source {name!r} in evaluation case {case['id']}")
        groups = case.get("user_groups", [])
        if not isinstance(groups, list) or any(group not in ACCESS_GROUPS for group in groups):
            raise InventoryError(f"Unknown access group in evaluation case {case['id']}")
        questions.append(case)
    if not questions:
        raise InventoryError("Evaluation set has no questions")
    return questions


def print_summary(documents: list[dict], questions: list[dict]) -> None:
    formats = Counter(doc["suffix"] for doc in documents)
    groups = Counter(group for doc in documents for group in doc["metadata"]["access"])
    statuses = Counter(doc["metadata"]["status"] for doc in documents)
    trusts = Counter(doc["metadata"]["trust"] for doc in documents)
    pii_count = sum(doc["metadata"].get("contains_pii", False) for doc in documents)
    question_types = Counter(case.get("type", "unspecified") for case in questions)
    answerable = sum(case["answerable"] for case in questions)

    print("Course corpus inventory (metadata only; file content was not opened)")
    print(f"Source files: {len(documents)}; evaluation questions: {len(questions)}")
    print(f"Formats: {dict(sorted(formats.items()))}")
    print(f"Access groups: {dict(sorted(groups.items()))}")
    print(f"Document status: {dict(sorted(statuses.items()))}")
    print(f"Trust labels: {dict(sorted(trusts.items()))}; PII-marked files: {pii_count}")
    print(f"Evaluation: {answerable} answerable, {len(questions) - answerable} unanswerable")
    print(f"Question types: {dict(sorted(question_types.items()))}")
    print("Manifest and evaluation source references: valid")


def main() -> None:
    try:
        metadata = load_metadata()
        documents = inventory_documents(metadata)
        questions = inventory_questions(metadata)
    except InventoryError as exc:
        print(f"Corpus inventory failed:{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print_summary(documents, questions)


if __name__ == "__main__":
    main()
