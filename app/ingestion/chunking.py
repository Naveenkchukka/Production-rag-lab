"""Structure-aware, token-bounded chunks for the first retrieval experiments."""

import re

import tiktoken


CHUNKING_VERSION = "structure-token-v2"
MAX_CHUNK_TOKENS = 350
OVERLAP_TOKENS = 50
_ENCODING = tiktoken.encoding_for_model("text-embedding-3-small")


def _split_oversized_line(line: str) -> list[str]:
    """Prefer sentence and word boundaries; never cut a token byte sequence."""
    if len(_ENCODING.encode(line)) <= MAX_CHUNK_TOKENS:
        return [line]

    sentences = [part.strip() for part in re.split(r"(?<=[.!?।！？])\s+", line) if part.strip()]
    pieces: list[str] = []
    for sentence in sentences:
        if len(_ENCODING.encode(sentence)) <= MAX_CHUNK_TOKENS:
            pieces.append(sentence)
            continue
        words = sentence.split()
        current: list[str] = []
        for word in words:
            candidate = " ".join(current + [word])
            if current and len(_ENCODING.encode(candidate)) > MAX_CHUNK_TOKENS:
                pieces.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
            if len(_ENCODING.encode(" ".join(current))) > MAX_CHUNK_TOKENS:
                raise ValueError("A single unbroken word exceeds the chunk token limit")
        if current:
            pieces.append(" ".join(current))
    return pieces


def _units(text: str) -> list[str]:
    units: list[str] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for paragraph in re.split(r"\n\s*\n", normalized):
        for raw_line in paragraph.splitlines():
            line = raw_line.strip()
            if not line or not re.search(r"\w", line, flags=re.UNICODE):
                continue
            units.extend(_split_oversized_line(line))
    return units


def chunk_text(text: str) -> list[tuple[str, int]]:
    """Group complete lines/sentences under a token limit with bounded overlap.

    The 350-token maximum and 50-token overlap are experimental baselines. The
    overlap includes only whole source units so chunks do not begin mid-word.
    """
    chunks: list[tuple[str, int]] = []
    current: list[str] = []

    def count(units: list[str]) -> int:
        return len(_ENCODING.encode("\n".join(units)))

    def emit(units: list[str]) -> None:
        if units:
            content = "\n".join(units).strip()
            if content:
                chunks.append((content, len(_ENCODING.encode(content))))

    def overlap_tail(units: list[str]) -> list[str]:
        tail: list[str] = []
        for unit in reversed(units):
            candidate = [unit] + tail
            if count(candidate) > OVERLAP_TOKENS:
                break
            tail = candidate
        return tail

    for unit in _units(text):
        if len(_ENCODING.encode(unit)) > MAX_CHUNK_TOKENS:
            raise ValueError("Chunk unit exceeds the configured token limit")
        candidate = current + [unit]
        if current and count(candidate) > MAX_CHUNK_TOKENS:
            emit(current)
            overlap = overlap_tail(current)
            while overlap and count(overlap + [unit]) > MAX_CHUNK_TOKENS:
                overlap.pop(0)
            current = overlap + [unit]
        else:
            current = candidate

    emit(current)
    return chunks
