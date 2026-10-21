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


def test_strips_page_header_furniture():
    """2023_6_56_84_EN.pdf's later pages open with "SUPREME COURT REPORTS\\n[YYYY] V S.C.R."
    — running-header print furniture, not judgment text."""
    pages = extract_pages(str(FIXTURES / "2023_6_56_84_EN.pdf"))
    assert "SUPREME COURT REPORTS" not in pages[1].text


def test_strips_own_title_footer_when_party_names_given():
    """Regression for a real bug found via M2's hand-marking walkthrough: this judgment's
    own title ("GODREJ AND BOYCE ... v. THE MUNICIPAL CORPORATION OF GREATER MUMBAI")
    repeats as a running footer mid-page, and citations/extract.py mistook it for a
    citation to a different case. Without petitioner/respondent, old behaviour is kept
    (nothing to fuzzy-match against); with them, the self-citation footer is stripped."""
    petitioner = (
        "GODREJ AND BOYCE MANUFACTURING COMPANY LIMITED THROUGH ITS CONSTITUTED ATTORNEY & ANR."
    )
    respondent = "THE MUNICIPAL CORPORATION OF GREATER MUMBAI & ORS"

    pages_without = extract_pages(str(FIXTURES / "2023_6_56_84_EN.pdf"))
    pages_with = extract_pages(str(FIXTURES / "2023_6_56_84_EN.pdf"), petitioner, respondent)

    assert "CONSTITUTED ATTORNEY v. THE MUNICIPAL CORPORATION OF" in pages_without[1].text
    assert "CONSTITUTED ATTORNEY v. THE MUNICIPAL CORPORATION OF" not in pages_with[1].text
