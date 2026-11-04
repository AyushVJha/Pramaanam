"""Probe: would SCC/AIR aliases derived from case names be good enough? (read-only)

For every SCC/AIR citation in a sample of judgments that has a tightly attached case name, resolve
it by name (fuzzy, score >= 0.9, unambiguous, never the citing judgment itself). Where the same
mention is also an ANCHORED alias (printed beside an SCR/neutral number, which we trust at 99%),
compare: that gives the precision of the name method. Also reports how many mentions the name
method adds beyond the anchored table.

Usage: uv run python scripts/alias_name_probe.py [n_cases]
"""

import sqlite3
import sys
from collections import Counter

from pramaan.citations.extract import extract
from pramaan.data.build_aliases import ALIAS_FORMATS, aliases_in_text
from pramaan.resolve.resolver import resolve_fuzzy

con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
n_cases = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
cases = [r[0] for r in con.execute(
    "SELECT cnr FROM cases WHERE year >= 1990 ORDER BY (rowid * 7919) % 10007 LIMIT ?", (n_cases,)
)]
stats: Counter = Counter()
name_votes: dict[tuple, Counter] = {}
for cnr in cases:
    for (text,) in con.execute("SELECT text FROM paragraphs WHERE case_id = ?", (cnr,)):
        if "SCC" not in text and "AIR" not in text:
            continue
        anchored = {(r[0], r[1], r[2], r[3]): r[4] for r in aliases_in_text(con, cnr, text)}
        for c in extract(text):
            if c.format not in ALIAS_FORMATS or not c.parsed or not c.case_name or not c.name_tight:
                continue
            p = c.parsed
            key = (p.reporter, p.year, p.volume, p.page)
            res = resolve_fuzzy(con, c.case_name, p.year, 0.9, exclude_case=cnr)
            if res.method != "fuzzy" or res.case_id is None:
                stats["name method: no answer"] += 1
                continue
            stats["name method: answer"] += 1
            name_votes.setdefault(key, Counter())[res.case_id] += 1
            if key in anchored:
                stats["answer, anchored truth known"] += 1
                stats["  of which right"] += res.case_id == anchored[key]
            else:
                stats["answer, no anchored truth (new coverage)"] += 1
for k, v in stats.items():
    print(f"{k}: {v}")
agree = [k for k, c in name_votes.items() if sum(c.values()) >= 2 and len(c) == 1]
print("keys with >=2 agreeing name votes and no conflict:", len(agree), "of", len(name_votes))
