from __future__ import annotations

import html
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".org",
    ".rst",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
EPUB_EXTENSIONS = {".epub"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS | EPUB_EXTENSIONS


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"p", "br", "div", "section", "chapter", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")


def _strip_html(markup: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(markup)
    return html.unescape(" ".join(parser.parts))


def _extract_epub_text(path: Path) -> str:
    html_suffixes = (".html", ".xhtml", ".htm")
    parts: list[str] = []
    if path.is_dir():
        for item in sorted(path.rglob("*")):
            if not item.is_file() or item.suffix.lower() not in html_suffixes:
                continue
            markup = item.read_text(encoding="utf-8", errors="ignore")
            text = _strip_html(markup)
            if text:
                parts.append(text)
        return "\n\n".join(parts)

    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(html_suffixes) and "meta-inf/" not in name.lower()
        ]
        for name in sorted(names):
            raw = archive.read(name)
            markup = raw.decode("utf-8", errors="ignore")
            text = _strip_html(markup)
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def is_supported(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return False
    return path.is_file() or (suffix == ".epub" and path.is_dir())


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError as exc:
            raise RuntimeError("PDF support needs: python3 -m pip install '.[pdf]'") from exc
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        try:
            import docx
        except ModuleNotFoundError as exc:
            raise RuntimeError("DOCX support needs: python3 -m pip install '.[docx]'") from exc
        document = docx.Document(str(path))
        return "\n\n".join(paragraph.text for paragraph in document.paragraphs)
    if suffix == ".epub":
        return _extract_epub_text(path)
    raise ValueError(f"Unsupported file type: {path}")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be larger than overlap")

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            paragraph_break = text.rfind("\n\n", start, end)
            sentence_break = max(text.rfind("。", start, end), text.rfind(".", start, end))
            cut = paragraph_break if paragraph_break > start + chunk_size * 0.55 else sentence_break
            if cut > start + chunk_size * 0.55:
                end = cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks
