"""pdf_text.py: real-PDF extraction and margin-letter stripping."""

from pathlib import Path

from pramaan.data.pdf_text import extract_pages

FIXTURES = Path(__file__).parent / "fixtures" / "pdfs"


def test_extracts_all_pages():
    pages = extract_pages(str(FIXTURES / "2023_1_907_912_EN.pdf"))
    assert len(pages) == 6
    assert all(p.text.strip() for p in pages)


def test_strips_margin_letters():
    """2023_10_936_976_EN.pdf's pages open with a vertical A B C D E F G H margin sequence
    (docs/DATA_NOTES.md §4) that isn't part of the judgment text."""
    pages = extract_pages(str(FIXTURES / "2023_10_936_976_EN.pdf"))
    first_page_lines = [line.strip() for line in pages[0].text.split("\n") if line.strip()]
    assert first_page_lines[:3] != ["A", "B", "C"]
    for letter in "ABCDEFGH":
        assert first_page_lines[0] != letter
