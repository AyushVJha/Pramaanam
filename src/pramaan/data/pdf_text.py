"""PyMuPDF text extraction from judgment PDFs, keeping page numbers.

Two kinds of print furniture leak into the plain-text extraction and get stripped here,
both found by tracing a real false-positive citation back to its source (see DECISIONS.md):

1. A running page-top header, "SUPREME COURT REPORTS\\n[YYYY] V S.C.R.\\n" — generic, the
   same on every judgment, stripped unconditionally (like the margin letters M0 found).
2. A running page-bottom/headnote footer that repeats the case's OWN title ("X v. Y"),
   SCR's print convention. This one needs the case's actual petitioner/respondent to strip
   safely by fuzzy match — otherwise we'd risk deleting a real mention of the parties'
   names from the judgment's own reasoning, not just the repeated masthead.
"""

import re

import pymupdf
from pydantic import BaseModel
from rapidfuzz import fuzz

from pramaan.citations.normalise import normalise_party_name

# A line that is just one of the margin letters A-H, alone, with nothing else on it.
_MARGIN_LETTER_LINE = re.compile(r"(?m)^[A-H]\s*$\n?")

_PAGE_HEADER = re.compile(r"SUPREME COURT REPORTS\s*\n\[\d{4}\]\s*\d{0,2}\s*S\.C\.R\.\s*\n?")

# Unlike citations.patterns.CASE_NAME, this isn't word-bounded: footer-stripping is gated
# by a fuzzy match against the case's own KNOWN party names (below), so the usual "might
# swallow a preceding clause" risk doesn't apply the same way here — a long corporate party
# name (e.g. "GODREJ AND BOYCE MANUFACTURING COMPANY LIMITED THROUGH ITS CONSTITUTED
# ATTORNEY") needs the unbounded form; in practice punctuation/digits in real surrounding
# text (citations, pincites) naturally firewall the match anyway.
_FOOTER_NAME_PART = r"[A-Z][A-Za-z.&'\-]*(?:\s+[A-Za-z.&'\-]+)*"
_FOOTER_CASE_NAME = re.compile(rf"{_FOOTER_NAME_PART}\s+v(?:s)?\.?\s+{_FOOTER_NAME_PART}")

_FOOTER_MATCH_THRESHOLD = 80.0


class PageText(BaseModel):
    page_no: int  # 1-indexed
    text: str


def _strip_margin_letters(text: str) -> str:
    return _MARGIN_LETTER_LINE.sub("", text)


def _strip_page_header(text: str) -> str:
    return _PAGE_HEADER.sub("", text)


def _strip_party_name_footer(text: str, petitioner: str, respondent: str) -> str:
    """Remove a CASE_NAME-shaped match only if both sides fuzzy-match this case's own
    petitioner/respondent — a real citation to a *different* case is left untouched."""
    norm_petitioner = normalise_party_name(petitioner)
    norm_respondent = normalise_party_name(respondent)

    def is_own_title(match: re.Match) -> bool:
        parts = re.split(r"\s+vs?\.?\s+", match.group(0), maxsplit=1, flags=re.IGNORECASE)
        if len(parts) != 2:
            return False
        left, right = (normalise_party_name(p) for p in parts)
        forward = (
            fuzz.token_set_ratio(left, norm_petitioner) >= _FOOTER_MATCH_THRESHOLD
            and fuzz.token_set_ratio(right, norm_respondent) >= _FOOTER_MATCH_THRESHOLD
        )
        reverse = (
            fuzz.token_set_ratio(left, norm_respondent) >= _FOOTER_MATCH_THRESHOLD
            and fuzz.token_set_ratio(right, norm_petitioner) >= _FOOTER_MATCH_THRESHOLD
        )
        return forward or reverse

    return _FOOTER_CASE_NAME.sub(lambda m: "" if is_own_title(m) else m.group(0), text)


def extract_raw_pages(pdf_path_or_bytes: str | bytes) -> list[PageText]:
    """Extract text per page exactly as PyMuPDF returns it, with no cleaning.

    This is what the permanent text layer stores (data/text_layer.py). Cleaning is applied
    afterwards by `clean_pages`, so the cleaning rules can change without re-reading PDFs.
    """
    if isinstance(pdf_path_or_bytes, bytes):
        doc = pymupdf.open(stream=pdf_path_or_bytes, filetype="pdf")
    else:
        doc = pymupdf.open(pdf_path_or_bytes)
    try:
        return [PageText(page_no=i + 1, text=page.get_text()) for i, page in enumerate(doc)]
    finally:
        doc.close()


def clean_pages(
    raw_pages: list[PageText],
    petitioner: str | None = None,
    respondent: str | None = None,
) -> list[PageText]:
    """Strip print-furniture noise from raw pages.

    `petitioner`/`respondent` (the case's own party names, from its metadata) are optional:
    when given, also strips the running footer that repeats the case's own title — without
    them, only the format-agnostic margin-letter and page-header stripping happens.
    """
    pages = []
    for raw in raw_pages:
        text = _strip_margin_letters(raw.text)
        text = _strip_page_header(text)
        if petitioner and respondent:
            text = _strip_party_name_footer(text, petitioner, respondent)
        pages.append(PageText(page_no=raw.page_no, text=text))
    return pages


def extract_pages(
    pdf_path_or_bytes: str | bytes,
    petitioner: str | None = None,
    respondent: str | None = None,
) -> list[PageText]:
    """Extract text per page from a judgment PDF, stripping print-furniture noise."""
    return clean_pages(extract_raw_pages(pdf_path_or_bytes), petitioner, respondent)


def extract_text(
    pdf_path_or_bytes: str | bytes,
    petitioner: str | None = None,
    respondent: str | None = None,
) -> str:
    """Extract the full judgment text (all pages joined), print furniture stripped."""
    return "\n".join(p.text for p in extract_pages(pdf_path_or_bytes, petitioner, respondent))
