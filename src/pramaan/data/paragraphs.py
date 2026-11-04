"""Split extracted judgment text into numbered paragraphs.

docs/DATA_NOTES.md §4 found SC judgments number paragraphs "N. " at the start of a line, but
a bare regex over that marker also matches stray numbers (page numbers, footnote refs) that
aren't real paragraph starts. The fix used here: only trust a run of marker lines whose
numbers strictly increase by 1 — a stray number breaks that run and gets excluded.

Text that is not in a numbered paragraph is KEPT, as unnumbered paragraphs with NEGATIVE numbers
(-k ... -1, in reading order, so numbers stay unique and sorted). Before this, everything ahead of
the first numbered paragraph was thrown away; a judgment whose numbering only starts near its end
lost almost all its text, and quotes from it looked like inventions (DATA_NOTES 31).
Real paragraph numbers are always positive, so the paragraph check can ignore unnumbered text.

When no such run exists (unnumbered judgment), the whole text is split on blank lines and numbered
the same negative way.
"""

import re
import unicodedata

from pydantic import BaseModel

from pramaan.data.pdf_text import PageText

_MARKER_LINE = re.compile(r"^(\d{1,3})\.\s+(.*)$")
MIN_RUN_LENGTH = 3  # shortest run of consecutive N, N+1, N+2, ... we trust as real numbering


class Paragraph(BaseModel):
    para_no: int
    page: int  # page the paragraph starts on
    text: str


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _lines_with_pages(pages: list[PageText]) -> list[tuple[int, str]]:
    out = []
    for page in pages:
        for line in page.text.split("\n"):
            out.append((page.page_no, line))
    return out


def _find_marker_run(lines: list[tuple[int, str]]) -> list[int]:
    """Return line indices whose leading number forms the longest trusted monotonic run."""
    candidates: list[tuple[int, int]] = []  # (line_index, number)
    for i, (_page, line) in enumerate(lines):
        m = _MARKER_LINE.match(line.strip())
        if m:
            candidates.append((i, int(m.group(1))))

    best_run: list[int] = []
    run: list[int] = []
    for pos, (i, n) in enumerate(candidates):
        if run and n == candidates[pos - 1][1] + 1:
            run.append(i)
        else:
            run = [i]
        if len(run) > len(best_run):
            best_run = run
    return best_run if len(best_run) >= MIN_RUN_LENGTH else []


def _split_by_markers(lines: list[tuple[int, str]], marker_indices: list[int]) -> list[Paragraph]:
    paragraphs = []
    for idx, start in enumerate(marker_indices):
        end = marker_indices[idx + 1] if idx + 1 < len(marker_indices) else len(lines)
        page_no, first_line = lines[start]
        m = _MARKER_LINE.match(first_line.strip())
        para_no = int(m.group(1))
        body_lines = [m.group(2)] + [line for _p, line in lines[start + 1 : end]]
        text = _normalise(" ".join(body_lines))
        if text:
            paragraphs.append(Paragraph(para_no=para_no, page=page_no, text=text))
    return paragraphs


def _unnumbered(blocks: list[tuple[int, str]]) -> list[Paragraph]:
    """(page, text) blocks -> paragraphs numbered -k ... -1 in reading order."""
    cleaned = [(page, _normalise(text)) for page, text in blocks]
    cleaned = [(page, text) for page, text in cleaned if text]
    k = len(cleaned)
    return [
        Paragraph(para_no=-(k - i), page=page, text=text) for i, (page, text) in enumerate(cleaned)
    ]


def _blocks_of(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Group lines into blocks separated by blank lines; a block carries the page it starts on."""
    blocks: list[tuple[int, str]] = []
    current: list[str] = []
    start_page = 0
    for page, line in lines:
        if line.strip():
            if not current:
                start_page = page
            current.append(line)
        elif current:
            blocks.append((start_page, " ".join(current)))
            current = []
    if current:
        blocks.append((start_page, " ".join(current)))
    return blocks


def _split_by_blank_lines(pages: list[PageText]) -> list[Paragraph]:
    return _unnumbered(_blocks_of(_lines_with_pages(pages)))


def split_paragraphs(pages: list[PageText]) -> list[Paragraph]:
    """Split a judgment's extracted pages into paragraphs, numbered where possible."""
    lines = _lines_with_pages(pages)
    marker_run = _find_marker_run(lines)
    if marker_run:
        front = _unnumbered(_blocks_of(lines[: marker_run[0]]))
        return front + _split_by_markers(lines, marker_run)
    return _split_by_blank_lines(pages)
