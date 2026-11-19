"""Locally extract text from the supplied corpus and print counts only."""

import csv
from html.parser import HTMLParser
import io
from pathlib import Path
import subprocess
import sys

import pypdfium2 as pdfium
from pypdf import PdfReader

from app.ingestion.inventory import RAW_DIR, load_metadata, inventory_documents


class VisibleTextParser(HTMLParser):
    """Collect visible HTML text while ignoring scripts and styles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def extract_text(path: Path, suffix: str) -> tuple[str, int | None]:
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        pdf = pdfium.PdfDocument(str(path))
        pages = []
        for page_index, source_page in enumerate(reader.pages):
            text = source_page.extract_text() or ""
            if not text.strip():
                page = pdf[page_index]
                bitmap = page.render(scale=2)
                image = bitmap.to_pil()
                image_data = io.BytesIO()
                image.save(image_data, format="PNG")
                result = subprocess.run(
                    ["tesseract", "stdin", "stdout", "-l", "eng"],
                    input=image_data.getvalue(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                text = result.stdout.decode("utf-8", errors="replace")
                image.close()
                bitmap.close()
                page.close()
            elif len(text.strip()) < 250 and source_page.images:
                # Mixed PDFs can have selectable text plus a scanned checklist
                # or form. OCR the embedded image when the page text is sparse.
                image_text = []
                for embedded_image in source_page.images:
                    result = subprocess.run(
                        ["tesseract", "stdin", "stdout", "-l", "eng"],
                        input=embedded_image.data,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=True,
                    )
                    recognized = result.stdout.decode("utf-8", errors="replace").strip()
                    if recognized:
                        image_text.append(recognized)
                if image_text:
                    text = text.rstrip() + "\n" + "\n".join(image_text)
            pages.append(text)
        pdf.close()
        return "\n".join(pages), len(reader.pages)
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    if suffix == ".html":
        parser = VisibleTextParser()
        parser.feed(content)
        return " ".join(parser.parts), None
    if suffix == ".csv":
        rows = csv.reader(io.StringIO(content))
        return "\n".join(" | ".join(cell for cell in row) for row in rows), None
    return content, None


def main() -> None:
    try:
        documents = inventory_documents(load_metadata())
        print("Local extraction preview (document text is not printed or uploaded)")
        total_chars = 0
        for document in documents:
            text, pages = extract_text(RAW_DIR / document["name"], document["suffix"])
            chars = len(text.strip())
            total_chars += chars
            page_info = f", pages={pages}" if pages is not None else ""
            status = "needs OCR review" if document["suffix"] == ".pdf" and chars == 0 else "ok"
            print(f"{document['name']}: chars={chars}{page_info}, extraction={status}")
        print(f"Total extracted characters: {total_chars}")
    except Exception as exc:
        print(f"Extraction preview failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
