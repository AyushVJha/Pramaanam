"""Central configuration: year ranges and file paths used by the data pipeline (M1)."""

from pathlib import Path

DATA_DIR = Path("data")
DB_PATH = Path("pramaan.db")

# `make db-sample` — matches what M0 already downloaded; fast, for development.
SAMPLE_YEARS = [2023]

# `make db` — the full corpus build (SPEC.md §2), decided for M1.
FULL_YEARS = list(range(2010, 2026))
