"""How accurate is the text layer stored in our database? (40 pages, Claude-labelled)

Ground truth is `bench/labels/claude_pages.jsonl`: one page from each of 40 judgments
(1955 to 2024), transcribed from the page image by Claude (claude-sonnet-5-5). NOT human-verified,
and Claude can misread print: report every number from this script as Claude-labelled.

For each page the transcription is cut into paragraphs, and each paragraph is scored against the
embedded PDF text of the same page: edit distance to the best-matching stretch, divided by the
paragraph length (the same measure as bench/eval_ocr_engines.py). Margin letters, running heads
and page furniture are not in the transcription, so they are not counted.

Usage: uv run python bench/eval_text_layer_pages.py
"""

import json
import statistics
from pathlib import Path

from bench.eval_ocr_engines import GT, best_substring_errors, normalise
from pramaan.data.pdf_text import extract_raw_pages

LABELS = Path("bench/labels/claude_pages.jsonl")


def main() -> None:
    rows = []
    for line in LABELS.read_text().splitlines():
        rec = json.loads(line)
        pdf = GT / "pdfs" / f"{rec['path']}_EN.pdf"
        pages = {p.page_no: p.text for p in extract_raw_pages(pdf.read_bytes())}
        engine = normalise(pages.get(rec["page"], ""))
        errors = chars = 0
        for block in rec["text"].split("\n"):
            block = normalise(block)
            if len(block) < 20:
                continue
            errors += best_substring_errors(block, engine)
            chars += len(block)
        rows.append((rec["path"], rec["page"], chars, errors / chars if chars else 1.0))
    rates = sorted(r[3] for r in rows)
    total_err = sum(r[2] * r[3] for r in rows)
    total_chars = sum(r[2] for r in rows)
    print(f"{len(rows)} pages, {total_chars} characters (Claude-labelled, not human-verified)")
    print(f"character error rate, pooled: {total_err / total_chars:.4f}")
    print(f"per page: median {statistics.median(rates):.4f}, "
          f"p90 {rates[int(0.9 * len(rates))]:.4f}, worst {rates[-1]:.4f}")
    print("pages above 2% error:")
    for path, page, chars, rate in sorted(rows, key=lambda r: -r[3]):
        if rate > 0.02:
            print(f"  {path} p{page}: {rate:.3f} ({chars} chars)")


if __name__ == "__main__":
    main()
