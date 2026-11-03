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

# --- LLM settings (M5). All model names live here, never inside the checks. ---
# Cheapest model first; move up only if it fails on the dev set (CLAUDE.md).
JUDGE_MODEL = os.environ.get("PRAMAAN_JUDGE_MODEL", "claude-haiku-5-5")
LLM_CACHE_DIR = Path(os.environ.get("PRAMAAN_LLM_CACHE_DIR", "data/llm_cache"))
LLM_USAGE_LOG = Path("logs/llm_usage.jsonl")

# US dollars per million tokens (input, output). Copied from Anthropic's price list;
# used only to ESTIMATE cost in the usage log. Check against the bill, do not trust blindly.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
