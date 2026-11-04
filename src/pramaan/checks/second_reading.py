"""Second, independent reading of a judgment for the quote check.

The primary text is the PDF's embedded OCR layer. Before we call a quote a MISQUOTE we look at the
layout layer (Docling + fresh OCR, DATA_NOTES 16) if it has been built for that judgment. A quote
absent from both readings is much stronger evidence than one absent from a single noisy reading.
Returns None when the layout layer is not available for the judgment.
"""

import sqlite3
from pathlib import Path

from pramaan.checks.quotes import QuoteResult, check_quote_in_paragraphs
from pramaan.config import DATA_DIR
from pramaan.data.layout import page_text
from pramaan.data.layout_store import layout_dir, read_blocks
from pramaan.data.paragraphs import split_paragraphs
from pramaan.data.pdf_text import PageText

BODY_LABELS = {"text", "list_item", "section_header"}  # not footnotes, tables or furniture


def second_reading(
    con: sqlite3.Connection, case_id: str, quote: str, data_dir: Path = DATA_DIR
) -> QuoteResult | None:
    row = con.execute("SELECT pdf_path FROM cases WHERE cnr = ?", (case_id,)).fetchone()
    if not row or not row[0]:
        return None
    stem = row[0].removesuffix(".pdf").removesuffix("_EN")
    try:
        year = int(stem.split("_")[0])
    except ValueError:
        return None
    blocks = read_blocks(layout_dir(year, data_dir=data_dir), stem)
    if not blocks:
        return None
    pages = [
        PageText(page_no=n, text=page_text(blocks, n, BODY_LABELS))
        for n in sorted({b.page for b in blocks})
    ]
    paragraphs = [(p.para_no, p.text) for p in split_paragraphs(pages)]
    return check_quote_in_paragraphs(paragraphs, quote)
