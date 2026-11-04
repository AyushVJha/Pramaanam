"""Stress test: feed whole real judgments to the pipeline as if they were drafts, list accusations.

A real judgment's citations are presumably accurate, so any MISQUOTE / NAME_MISMATCH /
WRONG_PARAGRAPH it raises is a suspected false accusation to read by hand. Read-only.
Usage: uv run python scripts/stress_real_text.py [n_judgments]
"""

import sqlite3
import sys
from collections import Counter

from pramaan.citations.extract import extract
from pramaan.pipeline import check_citation

n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
cases = con.execute(
    "SELECT cnr, title, year FROM cases WHERE year >= 1960 "
    "ORDER BY (rowid * 104729) % 10007 LIMIT ?", (n,),
).fetchall()
total: Counter = Counter()
accusations = []
for cnr, title, year in cases:
    text = "\n\n".join(r[0] for r in con.execute(
        "SELECT text FROM paragraphs WHERE case_id = ? ORDER BY para_no", (cnr,)))
    for c in extract(text):
        r = check_citation(con, c, use_llm=False, exclude_citing=cnr)
        total[r.status] += 1
        if r.status in ("MISQUOTE", "NAME_MISMATCH", "WRONG_PARAGRAPH"):
            accusations.append((year, title[:40], r.status, c.raw, c.case_name, r.reason[:160]))
print(dict(total))
print(f"{len(accusations)} accusations in {len(cases)} judgments")
for a in accusations:
    print(a)
