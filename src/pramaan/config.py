"""Central configuration: year ranges and file paths used by the data pipeline."""

import os
from pathlib import Path

# Where downloaded/derived data lives. Override with PRAMAAN_DATA_DIR (e.g. an external disk).
DATA_DIR = Path(os.environ.get("PRAMAAN_DATA_DIR", "data"))
DB_PATH = Path("pramaan.db")

# Permanent archive of the raw bucket files (an rclone remote path). Raw files are copied
# here once, so we never need to download from S3 again. See DECISIONS.md.
ARCHIVE_REMOTE = os.environ.get("PRAMAAN_ARCHIVE_REMOTE", "gdrive:pramaan-data")

# `make db-sample` — fast, for development.
SAMPLE_YEARS = [2023]

# `make db` — every year in the bucket (1950-2026). Measured on 2023 judgments: 56% of the
# authorities they cite were decided before 2010, so a 2010+ corpus misses most citations.
FULL_YEARS = list(range(1950, 2027))
