"""Measure how many citations inside judgment bodies can be resolved against the corpus.

Read-only. Scans every paragraph of pramaan.db, finds structured citations with the same
patterns the extractor uses, and reports per format how many resolve by exact lookup in
`case_citations` (SCR and neutral INSC only: the corpus has no SCC or AIR numbers).
A citation to the citing case itself is not counted.

Usage: uv run python scripts/measure_coverage.py [path/to/pramaan.db]
"""

import sqlite3
import sys
from collections import Counter

from pramaan.citations.normalise import parse_citation
from pramaan.citations.patterns import STRUCTURED

db_path = sys.argv[1] if len(sys.argv) > 1 else "pramaan.db"
con = sqlite3.connect(db_path)

# (reporter, year, volume, page) -> cnr. For INSC the volume is None.
index: dict[tuple, str] = {}
for cnr, reporter, year, volume, page in con.execute(
    "SELECT case_id, reporter, year, volume, page FROM case_citations"
):
    index[(reporter, year, volume, page)] = cnr

found: Counter = Counter()
resolved: Counter = Counter()
resolved_by_cited_decade: Counter = Counter()
total_by_cited_decade: Counter = Counter()
paras_with_scc_air = 0
paras_with_scc_air_and_resolvable = 0

for citing_cnr, text in con.execute("SELECT case_id, text FROM paragraphs"):
    resolvable_here = False
    has_scc_air = False
    for fmt, pattern in STRUCTURED.items():
        for m in pattern.finditer(text):
            parsed = parse_citation(m.group(0), fmt)
            if not parsed:
                continue
            found[fmt] += 1
            if fmt in ("SCC", "AIR", "SCC_ONLINE"):
                has_scc_air = has_scc_air or fmt in ("SCC", "AIR")
                continue
            key = (parsed.reporter, parsed.year, parsed.volume, parsed.page)
            target = index.get(key)
            decade = parsed.year // 10 * 10
            total_by_cited_decade[(fmt, decade)] += 1
            if target and target != citing_cnr:
                resolved[fmt] += 1
                resolved_by_cited_decade[(fmt, decade)] += 1
                resolvable_here = True
    if has_scc_air:
        paras_with_scc_air += 1
        if resolvable_here:
            paras_with_scc_air_and_resolvable += 1

print(f"corpus cases: {con.execute('SELECT COUNT(*) FROM cases').fetchone()[0]}")
print(f"{'format':<12}{'found':>10}{'resolved':>10}{'rate':>8}")
for fmt in STRUCTURED:
    n, r = found[fmt], resolved[fmt]
    rate = f"{100 * r / n:.1f}%" if fmt in ("SCR", "NEUTRAL") and n else "n/a"
    print(f"{fmt:<12}{n:>10}{r:>10}{rate:>8}")
print()
print("resolution rate for SCR / NEUTRAL by decade of the cited year")
for fmt in ("SCR", "NEUTRAL"):
    for decade in sorted({d for f, d in total_by_cited_decade if f == fmt}):
        t = total_by_cited_decade[(fmt, decade)]
        r = resolved_by_cited_decade[(fmt, decade)]
        print(f"  {fmt:<8}{decade}s  {r:>6}/{t:<6} {100 * r / t:5.1f}%")
print()
print(
    f"paragraphs citing SCC or AIR: {paras_with_scc_air}; of those, also containing a "
    f"resolvable SCR/INSC citation: {paras_with_scc_air_and_resolvable}"
)
