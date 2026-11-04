"""Score our extracted page text against the pages a human corrected.

Input : bench/data/ground_truth/human/<path>.json   (from the viewer's Download button)
        bench/data/ground_truth/sample.json         (decade and length band of each case)
Output: per-decade character error rate, flag rates, and a list of the worst pages.

Character error rate (CER) = edit distance(our text, human text) / length of human text, after
collapsing every run of whitespace to one space. Line breaks are therefore NOT counted as errors
here; paragraph boundaries are a separate measurement that this file does not make yet.
Only pages the human ticked "I checked this page" are scored; unreadable pages are counted apart.

Usage: uv run python bench/eval_text_layer.py
"""

import json
import re
import statistics
from collections import defaultdict

from rapidfuzz.distance import Levenshtein

from pramaan.config import DATA_DIR
from pramaan.data.pdf_text import extract_raw_pages

GT = DATA_DIR.parent / "bench" / "data" / "ground_truth"
_SPACE = re.compile(r"\s+")


def squash(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def cer(ours: str, human: str) -> float:
    """Edit distance per human character, ignoring differences in whitespace."""
    a, b = squash(ours), squash(human)
    if not b:
        return 0.0 if not a else 1.0
    return Levenshtein.distance(a, b) / len(b)


def main() -> None:
    sample = {c["path"]: c for c in json.loads((GT / "sample.json").read_text())["cases"]}
    by_decade: dict[int, list[float]] = defaultdict(list)
    flags = {"table": 0, "footnotes": 0, "unreadable": 0, "scored": 0}
    worst: list[tuple[float, str, int]] = []
    files = sorted((GT / "human").glob("*.json")) if (GT / "human").exists() else []
    for f in files:
        human = json.loads(f.read_text())
        path = human["path"]
        pdf = GT / "pdfs" / f"{path}_EN.pdf"
        raw = {p.page_no: p.text for p in extract_raw_pages(pdf.read_bytes())}
        for page in human["pages"]:
            if not page["checked"]:
                continue
            flags["table"] += page["has_table"]
            flags["footnotes"] += page["has_footnotes"]
            if page["unreadable"]:
                flags["unreadable"] += 1
                continue
            score = cer(raw.get(page["page"], ""), page["corrected_text"])
            by_decade[sample[path]["decade"]].append(score)
            worst.append((score, path, page["page"]))
            flags["scored"] += 1
    print(f"human files: {len(files)}; pages scored: {flags['scored']}")
    if not flags["scored"]:
        print("nothing to score yet (no checked pages in bench/data/ground_truth/human/)")
        return
    print(f"{'decade':<8}{'pages':>7}{'mean CER':>11}{'median CER':>12}{'max CER':>10}")
    for d in sorted(by_decade):
        v = by_decade[d]
        print(f"{d}s{'':<4}{len(v):>7}{statistics.mean(v):>11.4f}"
              f"{statistics.median(v):>12.4f}{max(v):>10.4f}")
    print(f"pages with a table: {flags['table']}; with footnotes: {flags['footnotes']}; "
          f"unreadable: {flags['unreadable']}")
    print("worst 10 pages (CER, case, page):")
    for score, path, page in sorted(worst, reverse=True)[:10]:
        print(f"  {score:.4f}  {path}  p{page}")


if __name__ == "__main__":
    main()
