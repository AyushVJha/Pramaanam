"""Compare text engines against the model-made page excerpts (EXPLORATORY, 10 pages).

Ground truth here is `bench/labels/claude_excerpts.json`: one block of body text per
page, transcribed from the page image by Claude, NOT checked by a human. Treat results as a first
look, not a measurement. Engines: the text embedded in the PDF, and Tesseract in three page
segmentation modes. Nothing was tuned on these pages.

Score = character error rate of the best-matching stretch of the engine's page text:
    edit distance(excerpt, best substring of engine text) / length of excerpt
so margin letters, running heads and the rest of the page around the excerpt are not counted.
Both sides are normalised first: line-end hyphen breaks are joined, curly quotes and dashes made
plain, whitespace collapsed.

Usage: uv run python bench/eval_ocr_engines.py
"""

import json
import re
import statistics
from pathlib import Path

import pymupdf

from pramaan.config import DATA_DIR
from pramaan.data.ocr import tesseract_text
from pramaan.data.pdf_text import extract_raw_pages

GT = DATA_DIR.parent / "bench" / "data" / "ground_truth"
LABELS = DATA_DIR.parent / "bench" / "labels" / "claude_excerpts.json"  # tracked in git
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "–": "-", "—": "-", "˝": '"'})


def normalise(text: str) -> str:
    text = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", "", text)  # "educa-\ntion" -> "education"
    text = text.translate(_QUOTES)
    return re.sub(r"\s+", " ", text).strip()


def best_substring_errors(needle: str, haystack: str) -> int:
    """Smallest edit distance between `needle` and ANY substring of `haystack`.

    Standard dynamic programming with a free start and a free end in the haystack: row 0 is all
    zeros (the match may begin anywhere), and the answer is the smallest value in the last row.
    """
    previous = [0] * (len(haystack) + 1)
    for i, a in enumerate(needle, start=1):
        current = [i] + [0] * len(haystack)
        for j, b in enumerate(haystack, start=1):
            current[j] = min(
                previous[j - 1] + (a != b),  # same letter, or one wrong letter
                previous[j] + 1,             # a letter of the excerpt is missing in the engine text
                current[j - 1] + 1,          # the engine text has an extra letter
            )
        previous = current
    return min(previous)


def cer(excerpt: str, engine_text: str) -> float:
    needle = normalise(excerpt)
    return best_substring_errors(needle, normalise(engine_text)) / len(needle)


def main() -> None:
    items = json.loads(LABELS.read_text())["items"]
    engines = ["embedded", "tesseract_psm3", "tesseract_psm4", "tesseract_psm6"]
    # Docling output is made by bench/docling_pages.py (needs a Python that has docling).
    docling = {}
    for mode in ("default", "ocr"):
        f = Path(f"logs/docling_{mode}.json")
        if f.exists():
            docling[f"docling_{mode}"] = json.loads(f.read_text())
            engines.append(f"docling_{mode}")
    scores: dict[str, list[float]] = {e: [] for e in engines}
    print(f"{'page':<26}" + "".join(f"{e:>16}" for e in engines))
    print("(Docling columns appear only if logs/docling_<mode>.json exists)")
    for it in items:
        pdf = GT / "pdfs" / f"{it['path']}_EN.pdf"
        doc = pymupdf.open(pdf)
        page = doc[it["page"] - 1]
        embedded = {p.page_no: p.text for p in extract_raw_pages(pdf.read_bytes())}
        texts = {
            "embedded": embedded[it["page"]],
            "tesseract_psm3": tesseract_text(page, 3),
            "tesseract_psm4": tesseract_text(page, 4),
            "tesseract_psm6": tesseract_text(page, 6),
        }
        doc.close()
        for name, saved in docling.items():
            texts[name] = saved[f"{it['path']}|{it['page']}"]["text"]
        row = {e: cer(it["excerpt"], texts[e]) for e in engines}
        for e in engines:
            scores[e].append(row[e])
        label = f"{it['path']} p{it['page']}"
        print(f"{label:<26}" + "".join(f"{row[e]:>16.3f}" for e in engines))
    print(f"{'mean':<26}" + "".join(f"{statistics.mean(scores[e]):>16.3f}" for e in engines))
    print(f"{'median':<26}" + "".join(f"{statistics.median(scores[e]):>16.3f}" for e in engines))
    print(f"{'worst':<26}" + "".join(f"{max(scores[e]):>16.3f}" for e in engines))


if __name__ == "__main__":
    main()
