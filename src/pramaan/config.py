"""Central configuration: year ranges and file paths used by the data pipeline."""

import os
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines from .env into the environment. Variables already set win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()  # before the settings below are read

# Where downloaded/derived data lives. Override with PRAMAAN_DATA_DIR (e.g. an external disk).
DATA_DIR = Path(os.environ.get("PRAMAAN_DATA_DIR", "data"))
DB_PATH = Path(os.environ.get("PRAMAAN_DB_PATH", "pramaan.db"))

# Permanent archive of the raw bucket files (an rclone remote path). Raw files are copied
# here once, so we never need to download from S3 again. See DECISIONS.md.
ARCHIVE_REMOTE = os.environ.get("PRAMAAN_ARCHIVE_REMOTE", "gdrive:pramaan-data")

# `make db-sample` — fast, for development.
SAMPLE_YEARS = [2023]

# `make db` — every year in the bucket (1950-2026). Measured on 2023 judgments: 56% of the
# authorities they cite were decided before 2010, so a 2010+ corpus misses most citations.
FULL_YEARS = list(range(1950, 2027))

# --- LLM settings (M5). All model names live here, never inside the checks. ---
# No budget for paid APIs, so the default judge is an open model run locally with Ollama.
# "anthropic" is still supported (set PRAMAAN_JUDGE_BACKEND=anthropic and a claude-* model name).
JUDGE_BACKEND = os.environ.get("PRAMAAN_JUDGE_BACKEND", "ollama")
JUDGE_MODEL = os.environ.get("PRAMAAN_JUDGE_MODEL", "qwen2.5:7b-instruct")
OLLAMA_URL = os.environ.get("PRAMAAN_OLLAMA_URL", "http://localhost:11434")
# Any server with an OpenAI-style /v1/chat/completions (llama.cpp's llama-server, vLLM, ...).
# Put the URL and key in .env, never in the repo.
OPENAI_URL = os.environ.get("PRAMAAN_OPENAI_URL", "")
OPENAI_API_KEY = os.environ.get("PRAMAAN_OPENAI_API_KEY", "")
# Path after the URL. Default is the OpenAI one; Gemini's compatible endpoint uses
# URL=https://generativelanguage.googleapis.com/v1beta/openai and PATH=/chat/completions
OPENAI_PATH = os.environ.get("PRAMAAN_OPENAI_PATH", "/v1/chat/completions")
LLM_CACHE_DIR = Path(os.environ.get("PRAMAAN_LLM_CACHE_DIR", "data/llm_cache"))
LLM_USAGE_LOG = Path("logs/llm_usage.jsonl")

# US dollars per million tokens (input, output). Copied from Anthropic's price list;
# used only to ESTIMATE cost in the usage log. Check against the bill, do not trust blindly.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
