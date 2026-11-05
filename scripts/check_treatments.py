"""Spot-check the treatments table against known pairs and a fixed random sample. (G3)

Not a benchmark: the sample is read by a person (or by me, and then it is "read by Claude, not
verified by a lawyer"). Prints known-pair results and 30 strong rows with their source line.
Usage: uv run python scripts/check_treatments.py
"""

import sqlite3

con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
KNOWN = [  # (earlier case title fragment, year, later case title fragment, year)
    ("JABALPUR", 1976, "PUTTASWAMY", 2017),
    ("SMS TEA ESTATES", 2011, "INTERPLAY BETWEEN ARBITRATION", 2023),
    ("N. RADHAKRISHNAN", 2009, "VIDYA DROLIA", 2020),
    ("BHATIA INTERNATIONAL", 2002, "BHARAT ALUMINIUM", 2012),
]
for early, ey, late, ly in KNOWN:
    hit = con.execute(
        "SELECT t.label FROM treatments t JOIN cases a ON a.cnr=t.cited_case "
        "JOIN cases b ON b.cnr=t.citing_case WHERE a.title LIKE ? AND a.year=? "
        "AND b.title LIKE ? AND b.year=? AND t.label IN ('overruled','partly overruled')",
        (f"%{early}%", ey, f"%{late}%", ly),
    ).fetchone()
    print(f"{'FOUND ' if hit else 'absent'} {early} ({ey}) overruled by {late} ({ly})")

print("\nrandom strong rows (fixed seed order):")
rows = con.execute(
    "SELECT a.title, a.year, b.title, b.year, t.label, t.snippet FROM treatments t "
    "JOIN cases a ON a.cnr=t.cited_case JOIN cases b ON b.cnr=t.citing_case "
    "WHERE t.label IN ('overruled','partly overruled','disapproved','held per incuriam') "
    "ORDER BY substr(t.snippet, 1, 7) || t.cited_case LIMIT 30"
).fetchall()
for a, ay, b, by, label, snip in rows:
    print(f"- {a[:55]} ({ay}) <- {label} by {b[:55]} ({by})\n    {snip[-170:]}")
