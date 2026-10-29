"""Extracción de texto desde EPUB y PDF."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".epub", ".pdf"}

_WHITESPACE_RE = re.compile(r"[ \t\u00a0]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…;:])\s+")


class ExtractionError(ValueError):
    """Error controlado durante la extracción del documento."""


@dataclass
class Chapter:
    index: int
    title: str
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "title": self.title,
            "chars": self.char_count,
        }


def _looks_like_extension(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def clean_text(text: str) -> str:
    """Normaliza saltos de línea, espacios y palabras cortadas por guion."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Une palabras divididas al final de línea: "extra-\nordinario".
    text = re.sub(r"-\n(?=[a-záéíóúüñ])", "", text)
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in block.split("\n")]
        merged = " ".join(line for line in lines if line)
        merged = re.sub(r"\s+", " ", merged).strip()
        if merged:
            paragraphs.append(merged)
    return "\n\n".join(paragraphs)


def chunk_text(text: str, size: int = 3000) -> list[str]:
    """Divide texto en fragmentos <= size respetando párrafos y frases."""
    if size < 100:
        raise ValueError("El tamaño de fragmento debe ser >= 100 caracteres")
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= size:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= size:
                current = candidate
            else:
                flush()
                current = paragraph
            continue

        # Párrafo demasiado largo: dividir por frases.
        for sentence in _SENTENCE_SPLIT_RE.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            while len(sentence) > size:
                if current:
                    flush()
                chunks.append(sentence[:size].strip())
                sentence = sentence[size:].strip()
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= size:
                current = candidate
            else:
                flush()
                current = sentence
    flush()
    return chunks


def _epub_toc_titles(toc: list) -> dict[str, str]:
    titles: dict[str, str] = {}

    def walk(entries: list) -> None:
        for entry in entries:
            if isinstance(entry, (tuple, list)) and len(entry) == 2:
                section, children = entry
                href = getattr(section, "href", None)
                title = getattr(section, "title", None)
                if href and title:
                    titles[href.split("#")[0]] = str(title)
                walk(list(children or []))
            else:
                href = getattr(entry, "href", None)
                title = getattr(entry, "title", None)
                if href and title:
                    titles[href.split("#")[0]] = str(title)

    walk(toc or [])
    return titles


def _toc_title_for(titles: dict[str, str], name: str) -> str | None:
    from urllib.parse import unquote

    normalised = unquote(name)
    if normalised in titles:
        return titles[normalised]
    basename = Path(normalised).name
    for href, title in titles.items():
        if Path(unquote(href)).name == basename:
            return title
    return None


def _epub_chapter_title(soup, fallback: str) -> str:
    for tag in ("h1", "h2", "h3"):
        node = soup.find(tag)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if 0 < len(text) <= 160:
                return text
    return fallback


def extract_epub(path: Path) -> list[Chapter]:
    try:
        import ebooklib
        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
        from ebooklib import epub
    except ImportError as exc:  # pragma: no cover - dependencias instaladas
        raise ExtractionError(f"Faltan dependencias para EPUB: {exc}") from exc

    try:
        book = epub.read_epub(str(path))
    except Exception as exc:
        raise ExtractionError(f"No se pudo abrir el EPUB: {exc}") from exc

    toc_titles = _epub_toc_titles(list(book.toc))
    chapters: list[Chapter] = []
    seen: set[str] = set()

    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        name = item.get_name()
        raw_properties = getattr(item, "properties", None) or []
        if isinstance(raw_properties, str):
            raw_properties = [raw_properties]
        properties = {str(value) for value in raw_properties}
        if "nav" in properties or idref == "nav" or Path(name).name.lower() in {
            "nav.xhtml",
            "nav.html",
            "toc.xhtml",
            "toc.html",
        }:
            continue
        if name in seen:
            continue
        seen.add(name)

        try:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
                soup = BeautifulSoup(item.get_content(), "lxml")
        except Exception:
            soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style", "nav", "noscript"]):
            tag.decompose()
        text = clean_text(soup.get_text("\n"))
        if len(text) < 20:
            continue
        fallback = _toc_title_for(toc_titles, name) or f"Capítulo {len(chapters) + 1}"
        title = _epub_chapter_title(soup, fallback)
        chapters.append(Chapter(index=len(chapters) + 1, title=title, text=text))

    if not chapters:
        raise ExtractionError("El EPUB no contiene texto extraíble")
    return chapters


def extract_pdf(path: Path) -> list[Chapter]:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - versión antigua
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError as exc:
            raise ExtractionError(f"Faltan dependencias para PDF: {exc}") from exc

    try:
        document = pymupdf.open(str(path))
    except Exception as exc:
        raise ExtractionError(f"No se pudo abrir el PDF: {exc}") from exc

    chapters: list[Chapter] = []
    try:
        for page_number, page in enumerate(document, start=1):
            try:
                raw = page.get_text("text")
            except Exception:
                raw = ""
            text = clean_text(raw)
            if len(text) < 20:
                continue
            first_line = text.split("\n", 1)[0].strip()
            if 0 < len(first_line) <= 100 and len(text) > len(first_line) + 20:
                title = first_line
            else:
                title = f"Página {page_number}"
            chapters.append(Chapter(index=len(chapters) + 1, title=title, text=text))
    finally:
        document.close()

    if not chapters:
        raise ExtractionError(
            "El PDF no contiene texto extraíble (¿es un PDF escaneado sin OCR?)"
        )
    return chapters


def extract_document(
    path: str | Path, max_chapters: int | None = None
) -> list[Chapter]:
    """Extrae capítulos/páginas de un EPUB o PDF."""
    path = Path(path)
    if not path.exists():
        raise ExtractionError(f"El archivo no existe: {path}")
    if not path.is_file():
        raise ExtractionError(f"La ruta no es un archivo: {path}")
    if not _looks_like_extension(path):
        raise ExtractionError(
            f"Extensión no soportada ({path.suffix or 'sin extensión'}). "
            "Usa .epub o .pdf"
        )

    if path.suffix.lower() == ".epub":
        chapters = extract_epub(path)
    else:
        chapters = extract_pdf(path)

    if max_chapters is not None and max_chapters > 0:
        chapters = chapters[:max_chapters]
    return chapters
