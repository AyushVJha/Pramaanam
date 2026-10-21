"""Paragraph splitter tests against 3 real judgments (CC-BY-4.0, 2023 corpus).

Expected counts/behaviour below were hand-checked against each PDF's actual text, not
guessed — see the comment on each fixture for what was verified and why.
"""

from pathlib import Path

from pramaan.data.paragraphs import split_paragraphs
from pramaan.data.pdf_text import extract_pages

FIXTURES = Path(__file__).parent / "fixtures" / "pdfs"


def _paragraphs(filename: str):
    return split_paragraphs(extract_pages(str(FIXTURES / filename)))


def test_margin_letter_layout_full_run():
    """2023_10_936_976_EN.pdf: clean numbering 1-33, no HEADNOTES block, no quoted material.

    The real judgment body runs from "1. The core question..." to "33. ..."; hand-counted
    33 numbered paragraphs in the source PDF.
    """
    paras = _paragraphs("2023_10_936_976_EN.pdf")
    assert len(paras) == 33
    assert [p.para_no for p in paras] == list(range(1, 34))
    assert paras[0].text.startswith("The core question that arises")


def test_short_headnote_layout_strips_frontmatter():
    """2023_1_907_912_EN.pdf: short judgment, CASE DETAILS header before para 1.

    Hand-checked: the real judgment is exactly 4 numbered paragraphs ("Feeling aggrieved..."
    through the final order); the case header/citation block before "1." must not appear in
    paragraph 1's text.
    """
    paras = _paragraphs("2023_1_907_912_EN.pdf")
    assert [p.para_no for p in paras] == [1, 2, 3, 4]
    assert paras[0].text.startswith("Feeling aggrieved and dissatisfied")
    assert "CASE DETAILS" not in paras[0].text
    assert "S.C.R." not in paras[0].text


def test_quoted_material_with_own_numbering_is_a_known_limitation():
    """2023_15_848_865_EN.pdf: a KNOWN HARD CASE, documented rather than silently "fixed".

    The real judgment numbers 1-31 continuously, but paragraph 7 quotes an affidavit whose
    own internal numbering ("4. Since, as stated above...", "5. ...", "6. ...", "7. ...")
    collides with the outer sequence. Our "longest monotonic run" heuristic picks the run
    that reaches the true end of the judgment (31) over the short, genuine opening run
    (1-7), so paragraphs 1-4 (the procedural recitation: "Leave granted.", etc.) are lost.

    This test locks in and documents that known behaviour — see docs/DATA_NOTES.md and
    DECISIONS.md — rather than hiding it; a smarter heuristic is future work, not M1 scope.

    Separately: the last paragraph runs to end-of-document, so it also picks up the SCR
    footer ("Headnotes prepared by: ...") after the real final sentence — another known,
    minor imperfection of this M1 splitter, also documented rather than patched over.
    """
    paras = _paragraphs("2023_15_848_865_EN.pdf")
    assert paras[0].para_no == 5
    assert paras[-1].para_no == 31
    assert paras[-1].text.startswith("Appeal stands dismissed accordingly.")
