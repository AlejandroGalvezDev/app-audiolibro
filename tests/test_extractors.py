from __future__ import annotations

import pymupdf
import pytest
from ebooklib import epub

from app.extractors import (
    ExtractionError,
    chunk_text,
    clean_text,
    extract_document,
)


def _build_epub(path, chapters):
    book = epub.EpubBook()
    book.set_identifier("audiolibro-test-001")
    book.set_title("Libro de prueba")
    book.set_language("es")
    items = []
    for index, (title, body) in enumerate(chapters, start=1):
        item = epub.EpubHtml(title=title, file_name=f"chap_{index:02d}.xhtml", lang="es")
        item.content = (
            f"<html><body><h1>{title}</h1><p>{body}</p>"
            f"<p>Segundo párrafo del capítulo {index}.</p></body></html>"
        )
        book.add_item(item)
        items.append(item)
    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]
    epub.write_epub(str(path), book)


@pytest.fixture()
def sample_epub(tmp_path):
    path = tmp_path / "libro.epub"
    _build_epub(
        path,
        [
            ("El comienzo", "Había una vez un servidor que leía libros."),
            ("La travesía", "Después de muchos capítulos llegó el silencio."),
        ],
    )
    return path


@pytest.fixture()
def sample_pdf(tmp_path):
    path = tmp_path / "libro.pdf"
    document = pymupdf.open()
    for index in range(1, 3):
        page = document.new_page()
        page.insert_text(
            (72, 72),
            f"Chapter {index} of the test PDF.\nThis page contains enough text to be extracted.",
        )
        page.insert_text(
            (72, 120),
            "The quick brown fox jumps over the lazy dog again and again.",
        )
    document.save(str(path))
    document.close()
    return path


def test_extract_epub_chapters(sample_epub):
    chapters = extract_document(sample_epub)
    assert len(chapters) == 2
    assert chapters[0].title == "El comienzo"
    assert "servidor que leía libros" in chapters[0].text
    assert chapters[1].title == "La travesía"
    assert "silencio" in chapters[1].text
    assert all(chapter.text for chapter in chapters)


def test_extract_pdf_pages(sample_pdf):
    chapters = extract_document(sample_pdf)
    assert len(chapters) == 2
    assert "test PDF" in chapters[0].text
    assert chapters[0].index == 1
    assert chapters[1].index == 2


def test_extract_respects_max_chapters(sample_epub):
    chapters = extract_document(sample_epub, max_chapters=1)
    assert len(chapters) == 1


def test_extract_unsupported_extension(tmp_path):
    path = tmp_path / "nota.txt"
    path.write_text("hola", encoding="utf-8")
    with pytest.raises(ExtractionError, match="Extensión no soportada"):
        extract_document(path)


def test_extract_missing_file(tmp_path):
    with pytest.raises(ExtractionError, match="no existe"):
        extract_document(tmp_path / "fantasma.epub")


def test_clean_text_joins_hyphenated_words():
    cleaned = clean_text("extra-\nordinario\n\nsegundo   párrafo")
    assert "extraordinario" in cleaned
    assert "segundo párrafo" in cleaned


def test_chunk_text_respects_size_and_content():
    text = " ".join(f"Frase número {index}." for index in range(500))
    chunks = chunk_text(text, size=500)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert " ".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_chunk_text_hard_splits_long_sentence():
    chunks = chunk_text("a" * 1200, size=500)
    assert len(chunks) == 3
    assert all(len(chunk) <= 500 for chunk in chunks)


def test_chunk_text_empty():
    assert chunk_text("   ", size=500) == []
