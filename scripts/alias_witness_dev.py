"""Dev split only: how often is an alias answer right, by how many judgments back it? (read-only)

An alias answer maps an SCC/AIR number to a case using parallel citations printed in OTHER
judgments. 'Witnesses' are the distinct citing judgments printing that exact pair, not counting
the benchmark item's own judgment. Prints counts of (witnesses, outcome); 3 means 3 or more.

Usage: uv run python scripts/alias_witness_dev.py
"""

import sqlite3
import sys
from collections import Counter

sys.path.insert(0, "bench")
from eval_resolve import load, outcome, run  # noqa: E402

from pramaan.citations.normalise import parse_citation  # noqa: E402
from pramaan.resolve.resolver import DEFAULT_THRESHOLD  # noqa: E402

con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
table: Counter = Counter()
for item, res in run(con, load("dev"), DEFAULT_THRESHOLD):
    if res.method != "alias":
        continue
    p = parse_citation(item["cited_raw"], item["cited_format"])
    witnesses = con.execute(
        "SELECT COUNT(DISTINCT citing_case) FROM citation_aliases WHERE reporter = ? AND year = ? "
        "AND volume IS ? AND page = ? AND case_id = ? AND citing_case != ?",
        (p.reporter, p.year, p.volume, p.page, res.case_id, item["citing_case"]),
    ).fetchone()[0]
    table[(min(witnesses, 3), outcome(item, res))] += 1
for key in sorted(table):
    print(key, table[key])
