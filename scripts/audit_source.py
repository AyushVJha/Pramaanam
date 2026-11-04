"""Source audit (read-only): is the corpus complete, and where are the holes? (re-plan step 2)

Two independent completeness checks that do not depend on trusting the dataset's own counts:

1. SCR page tiling. File names encode year, volume, first page and last page
   ("1950_1_806_821_EN.pdf", or "S_1959_1_1_10_EN.pdf"). The judgments in a law-report volume sit
   one after another, so a gap between one judgment's last page and the next one's first page
   means a judgment (or some non-judgment pages) is not in the corpus. We list the gaps.
   Limits: it cannot see missing judgments at the very end of a volume, and gaps can also be
   index pages, editorial notes or blank pages. Small gaps (1-2 pages) are therefore reported
   separately from larger ones.
2. Neutral citation sequence (2023 onward): numbers are issued 1..N each year, so N minus the
   count of distinct numbers present is a lower bound on what is missing.

Also: duplicate page ranges and files with no recognisable name.
Writes logs/audit_gaps.csv. Usage: uv run python scripts/audit_source.py
"""

import csv
import re
import sqlite3
from collections import defaultdict

NAME = re.compile(r"^(?:[A-Za-z]+_)?(\d{4})_(\d+)_(\d+)_(\d+)_EN\.pdf$")
SMALL_GAP = 2  # pages; at or under this, a gap is more likely blank/furniture than a judgment

con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
rows = con.execute("SELECT cnr, pdf_path, substr(decision_date, -4) FROM cases").fetchall()

volumes: dict[tuple[int, int], list[tuple[int, int, str]]] = defaultdict(list)
unnamed = []
for cnr, path, _ in rows:
    m = NAME.match(path or "")
    if not m:
        unnamed.append(path)
        continue
    year, vol, start, end = map(int, m.groups())
    volumes[(year, vol)].append((start, end, cnr))

recognised = len(rows) - len(unnamed)
print(f"cases: {len(rows)}; recognisable file names: {recognised}; other: {len(unnamed)}")
if unnamed:
    print("  examples of other names:", unnamed[:5])

gaps = []  # (year, volume, after_page, before_page, missing_pages)
duplicates = 0
bad_ranges = 0
covered = defaultdict(int)
# per decade: volumes, pages covered, small gaps, big gaps, pages inside big gaps
by_decade = defaultdict(lambda: [0, 0, 0, 0, 0])
for (year, vol), items in sorted(volumes.items()):
    items.sort()
    prev_end = None
    seen = set()
    d = by_decade[year // 10 * 10]
    d[0] += 1
    for start, end, cnr in items:
        if end < start:
            bad_ranges += 1
            continue
        if (start, end) in seen:
            duplicates += 1
        seen.add((start, end))
        d[1] += end - start + 1
        if prev_end is not None and start > prev_end + 1:
            missing = start - prev_end - 1
            gaps.append((year, vol, prev_end, start, missing))
            if missing <= SMALL_GAP:
                d[2] += 1
            else:
                d[3] += 1
                d[4] += missing
        prev_end = max(prev_end or 0, end)

print(f"\nvolumes: {len(volumes)}; duplicate ranges: {duplicates}; inverted ranges: {bad_ranges}")
header = ["decade", "volumes", "pages", "small gaps", "big gaps", "pages in big gaps", "% of pages"]
print("".join(f"{h:<8}" if i == 0 else f"{h:>18}" for i, h in enumerate(header)))
for decade, (nv, pages, small, big, bigp) in sorted(by_decade.items()):
    share = 100 * bigp / (pages + bigp) if pages else 0
    print(f"{decade}s{'':<3}{nv:>18}{pages:>18}{small:>18}{big:>18}{bigp:>18}{share:>17.1f}%")
tot_big = sum(v[3] for v in by_decade.values())
tot_pages = sum(v[4] for v in by_decade.values())
print(f"\ntotal big gaps (> {SMALL_GAP} pages): {tot_big}, holding {tot_pages} pages")
sizes = sorted(g[4] for g in gaps if g[4] > SMALL_GAP)
if sizes:
    p90 = sizes[int(len(sizes) * 0.9)]
    print(f"big-gap size (pages): median {sizes[len(sizes) // 2]}, 90th percentile {p90}, "
          f"max {sizes[-1]}")

with open("logs/audit_gaps.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["year", "volume", "last_page_before", "first_page_after", "missing_pages"])
    w.writerows(gaps)

print("\nNeutral citation sequence (numbers issued 1..N each year).")
print("NOTE: before 2014 the numbers are contiguous because the dataset itself numbered the")
print("old judgments in order, so that range says nothing about completeness. 2014 on is")
print("informative. A highest number more than 1.5x the next one is flagged as a likely typo.")
print(f"{'year':<6}{'highest':>9}{'present':>9}{'missing':>9}{'missing %':>11}  note")
by_year = defaultdict(list)
for year, page in con.execute(
    "SELECT DISTINCT year, page FROM case_citations WHERE reporter = 'INSC'"
):
    by_year[year].append(page)
for year in sorted(by_year):
    nums = sorted(by_year[year])
    hi, note = nums[-1], ""
    if len(nums) > 1 and hi > nums[-2] * 1.5:
        note = f"outlier {hi} ignored"
        hi = nums[-2]
        nums = nums[:-1]
    if year >= 2014:
        miss = hi - len(nums)
        print(f"{year:<6}{hi:>9}{len(nums):>9}{miss:>9}{100 * miss / hi:>10.0f}%  {note}")
