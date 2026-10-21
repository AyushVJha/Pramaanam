"""M0 data inspection (SPEC.md §3.2): print what `citation` and `nc_display` actually contain,
across the downloaded metadata years, before any resolver design happens.

Run: uv run python scripts/inspect_metadata.py
"""

import random
import re
from pathlib import Path

import pandas as pd

METADATA_YEARS = [2022, 2023, 2024]
DATA_DIR = Path("data/metadata")

# Rough per-format regexes, from SPEC.md Appendix A, used only to classify `citation`
# strings for a frequency table — not the real extraction patterns (that's M2).
FORMAT_PATTERNS = {
    "neutral_insc": re.compile(r"\b(19|20)\d{2}\s*INSC\s*\d{1,5}\b", re.IGNORECASE),
    "scc": re.compile(r"\(\s*(19|20)\d{2}\s*\)\s*\d{1,2}\s+SCC\s+\d{1,4}"),
    "scc_online": re.compile(r"\b(19|20)\d{2}\s+SCC\s+OnLine\s+SC\s+\d{1,5}\b", re.IGNORECASE),
    "air": re.compile(r"\bAIR\s+(19|20)\d{2}\s+SC\s+\d{1,5}\b", re.IGNORECASE),
    "scr": re.compile(
        r"[\[\(]\s*(19|20)\d{2}\s*[\]\)]\s*(\d{1,2}\s+)?(Supp\.?\s*)?(\(\d\)\s*)?"
        r"S\.?\s?C\.?\s?R\.?\s+\d{1,4}"
    ),
}


def load_years(years: list[int]) -> dict[int, pd.DataFrame]:
    frames = {}
    for year in years:
        path = DATA_DIR / f"year={year}" / "metadata.parquet"
        frames[year] = pd.read_parquet(path)
    return frames


def pct_empty(series: pd.Series) -> float:
    empty = series.isna() | (series.astype(str).str.strip() == "")
    return 100.0 * empty.sum() / len(series)


def classify_citation(value: str) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return ["EMPTY"]
    hits = [name for name, pat in FORMAT_PATTERNS.items() if pat.search(value)]
    return hits or ["UNRECOGNISED"]


def main() -> None:
    random.seed(0)
    frames = load_years(METADATA_YEARS)

    print("=" * 70)
    print("ROW COUNTS PER YEAR")
    print("=" * 70)
    for year, df in frames.items():
        print(f"  {year}: {len(df)} rows")

    print()
    print("=" * 70)
    print("% EMPTY — citation / nc_display (per year)")
    print("=" * 70)
    for year, df in frames.items():
        print(
            f"  {year}: citation={pct_empty(df['citation']):.1f}%  "
            f"nc_display={pct_empty(df['nc_display']):.1f}%"
        )

    all_df = pd.concat(frames.values(), ignore_index=True)

    print()
    print("=" * 70)
    print("CITATION FORMAT FREQUENCY (regex classification, all years combined)")
    print("=" * 70)
    counts: dict[str, int] = {}
    for value in all_df["citation"]:
        for label in classify_citation(value):
            counts[label] = counts.get(label, 0) + 1
    total = len(all_df)
    for label, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {label:15s} {n:5d}  ({100.0 * n / total:.1f}%)")

    print()
    print("=" * 70)
    print("30 RANDOM EXAMPLES — citation, nc_display, title, petitioner, respondent")
    print("=" * 70)
    sample = all_df.sample(n=min(30, len(all_df)), random_state=0)
    for i, row in enumerate(sample.itertuples(), 1):
        print(f"\n--- example {i} (year={row.year}) ---")
        print(f"  citation:    {row.citation!r}")
        print(f"  nc_display:  {row.nc_display!r}")
        print(f"  case_id:     {row.case_id!r}")
        print(f"  title:       {row.title!r}")
        print(f"  petitioner:  {row.petitioner!r}")
        print(f"  respondent:  {row.respondent!r}")


if __name__ == "__main__":
    main()
