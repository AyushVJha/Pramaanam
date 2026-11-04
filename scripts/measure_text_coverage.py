"""How much of each PDF's text reaches the database, and are there PDFs with no text? Read-only.

For a few sample years: share of PDFs where over half the pages have under 30 characters (a scan
with no text layer), median share of empty pages, and the median share of the raw page text that
ends up in `paragraphs` (the rest is headnotes, front matter, stripped print furniture).
Usage: uv run python scripts/measure_text_coverage.py
"""

import sqlite3
import statistics

import pyarrow.parquet as pq

con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
print(f"{'year':<6}{'pdfs':>6}{'mostly-empty':>14}{'median empty pages':>20}{'text kept in DB':>17}")
for year in (1955, 1965, 1975, 1985, 1995, 2005, 2015, 2023):
    t = pq.read_table(f"data/text/year={year}/pages.parquet").to_pandas()
    t["n"] = t["text"].str.len()
    g = t.groupby("path").agg(
        pages=("page_no", "count"), chars=("n", "sum"), empty=("n", lambda s: (s < 30).sum())
    )
    mostly_empty = (g["empty"] / g["pages"] > 0.5).sum()
    ratios = []
    for path, row in g.sample(min(len(g), 80), random_state=1).iterrows():
        found = con.execute(
            "SELECT cnr FROM cases WHERE pdf_path LIKE ? LIMIT 1", (f"%{path}%",)
        ).fetchone()
        if not found or not row["chars"]:
            continue
        kept = con.execute(
            "SELECT COALESCE(SUM(LENGTH(text)), 0) FROM paragraphs WHERE case_id = ?", (found[0],)
        ).fetchone()[0]
        ratios.append(kept / row["chars"])
    empty_pct = (g["empty"] / g["pages"]).median() * 100
    kept_pct = 100 * statistics.median(ratios) if ratios else float("nan")
    print(
        f"{year:<6}{len(g):>6}{100 * mostly_empty / len(g):>13.1f}%{empty_pct:>19.1f}%"
        f"{kept_pct:>16.0f}%"
    )
