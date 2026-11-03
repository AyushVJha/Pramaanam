"""Measure how real quotes between judgments fare in the quote check (M4). No labels, no tuning.

Judgments quote earlier judgments: 'In X v. Y, [2001] 1 SCR 1, the Court held "...".'
For quotes sitting next to an SCR or neutral citation that resolves exactly to one case in the
corpus, this checks the quote against that case and counts the statuses.

Reading the numbers: "verbatim" means the text really is in the cited case. "not_found" is an
upper bound on misquotes: it also counts a quote that belongs to a different case than the
nearest citation, a paraphrase put in quote marks, and OCR damage in either text. Nothing here
is hand-checked, so it is a rate, not an accuracy.

Usage: uv run python bench/measure_real_quotes.py [N]
"""

import hashlib
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict

from pramaan.checks import quotes
from pramaan.checks.quotes import check_quote, split_segments
from pramaan.citations.extract import extract
from pramaan.resolve.resolver import lookup_exact

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
_QUOTE = re.compile(r"[\"\u201c]([^\"\u201c\u201d]{40,}?)[\"\u201d]")
_FOOTNOTE_MARK = re.compile(r"\(\s*\d{1,2}\s*\)\s*$")
MAX_GAP = 80  # characters between the closing quote mark and the citation


def quote_before(text: str, cite_start: int) -> str | None:
    """A quotation that ends shortly before the citation, with no other quote mark between."""
    best = None
    for m in _QUOTE.finditer(text[:cite_start]):
        if 0 <= cite_start - m.end() <= MAX_GAP and '"' not in text[m.end() : cite_start]:
            best = m.group(1)
    return best


def main() -> None:
    con = sqlite3.connect("pramaan.db")
    pairs: list[tuple[str, str, str]] = []  # (citing case, cited case, quote)
    for citing, text in con.execute("SELECT case_id, text FROM paragraphs WHERE text LIKE '%\"%' "
                                    "OR text LIKE '%“%'"):
        for c in extract(text):
            if not (c.parsed and c.format in ("SCR", "NEUTRAL")):
                continue
            if _FOOTNOTE_MARK.search(text[max(0, c.span[0] - 8) : c.span[0]]):
                continue  # a footnote at the foot of the page: its quote is in the body, far away
            quote = quote_before(text, c.span[0])
            if quote and split_segments(quote):
                hits = lookup_exact(con, c.parsed)
                if len(hits) == 1 and hits[0].case_id != citing:
                    pairs.append((citing, hits[0].case_id, quote))
    pairs = sorted(set(pairs), key=lambda p: hashlib.sha256("".join(p).encode()).hexdigest())
    print(f"quotes ending just before a resolvable SCR/neutral citation: {len(pairs)}; "
          f"checking {min(N, len(pairs))}")
    quotes.NEAR_THRESHOLD = 50  # keep weak matches too, to show how close the misses are
    closeness: Counter = Counter()
    by_decade: dict[int, Counter] = defaultdict(Counter)
    total: Counter = Counter()
    t = time.time()
    for citing, cited, quote in pairs[:N]:
        res = check_quote(con, cited, quote)
        sim = res.similarity * 100
        closeness["verbatim (100)" if res.status == "verbatim" else
                  "85-99" if sim >= 85 else "70-84" if sim >= 70 else
                  "50-69" if sim >= 50 else "no similar passage (<50)"] += 1
        if res.status == "near_match" and sim < 85:
            res = res.model_copy(update={"status": "not_found"})
        year = con.execute("SELECT year FROM cases WHERE cnr=?", (cited,)).fetchone()[0]
        by_decade[year // 10 * 10][res.status] += 1
        total[res.status] += 1
    n = sum(total.values())
    print(f"\nall: {n} checked in {time.time() - t:.0f} s")
    for k, v in total.most_common():
        print(f"  {k:<11}{v:>6}  {100 * v / n:5.1f}%")
    print("\nbest similarity between the quote and any passage of the cited case")
    for k in ("verbatim (100)", "85-99", "70-84", "50-69", "no similar passage (<50)"):
        print(f"  {k:<26}{closeness[k]:>6}  {100 * closeness[k] / n:5.1f}%")
    print("\nby decade of the CITED case")
    for d in sorted(by_decade):
        c = by_decade[d]
        m = sum(c.values())
        print(f"  {d}s  n={m:<4} verbatim {100 * c['verbatim'] / m:5.1f}%  "
              f"near {100 * c['near_match'] / m:5.1f}%  not found {100 * c['not_found'] / m:5.1f}%")


if __name__ == "__main__":
    main()
