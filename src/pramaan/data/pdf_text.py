"""PyMuPDF text extraction from judgment PDFs, keeping page numbers.

M0's docs/DATA_NOTES.md §4 found that pages carry a vertical "A B C D E F G H" margin-letter
sequence (SCR pincite line-markers) that isn't part of the judgment's actual text — this
module strips those before paragraph splitting sees the text.
"""

import re

import pymupdf
from pydantic import BaseModel

# A line that is just one of the margin letters A-H, alone, with nothing else on it.
_MARGIN_LETTER_LINE = re.compile(r"(?m)^[A-H]\s*$\n?")


class PageText(BaseModel):
    page_no: int  # 1-indexed
    text: str


def _strip_margin_letters(text: str) -> str:
    return _MARGIN_LETTER_LINE.sub("", text)


def extract_pages(pdf_path_or_bytes: str | bytes) -> list[PageText]:
    """Extract text per page from a judgment PDF, stripping margin-letter noise."""
    if isinstance(pdf_path_or_bytes, bytes):
        doc = pymupdf.open(stream=pdf_path_or_bytes, filetype="pdf")
    else:
        doc = pymupdf.open(pdf_path_or_bytes)
    try:
        return [
            PageText(page_no=i + 1, text=_strip_margin_letters(page.get_text()))
            for i, page in enumerate(doc)
        ]
    finally:
        doc.close()


def extract_text(pdf_path_or_bytes: str | bytes) -> str:
    """Extract the full judgment text (all pages joined), margin letters stripped."""
    return "\n".join(p.text for p in extract_pages(pdf_path_or_bytes))
