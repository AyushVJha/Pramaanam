"""Download metadata parquet and judgment tars from the public `indian-supreme-court-judgments`
S3 bucket (CC-BY-4.0, no AWS credentials needed — see SPEC.md §3.1).
"""

import logging
import shutil
from pathlib import Path

from pramaan.config import DATA_DIR, SAMPLE_YEARS
from pramaan.data.retry import run_with_retry

logger = logging.getLogger(__name__)

BUCKET = "indian-supreme-court-judgments"
REGION = "ap-south-1"


def _aws_s3_cp(key: str, dest: Path) -> None:
    """Copy one object from the public bucket to `dest`, skipping it if already present."""
    if dest.exists():
        logger.info("skip (already downloaded): %s", dest)
        return
    if shutil.which("aws") is None:
        raise RuntimeError(
            "aws CLI not found on PATH. Install it (e.g. `brew install awscli`) — "
            "SPEC.md §3.1 relies on `aws s3 cp --no-sign-request` for anonymous access."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"s3://{BUCKET}/{key}"
    logger.info("downloading %s -> %s", url, dest)
    # `aws s3 cp` writes to a temporary name and renames on completion, so a dropped
    # connection never leaves a half-written file at `dest` (which the skip check above
    # would wrongly treat as done).
    run_with_retry(
        ["aws", "s3", "cp", url, str(dest), "--no-sign-request", "--region", REGION,
         "--no-progress"],
        f"download {key}",
    )


def download_metadata(years: list[int]) -> list[Path]:
    """Fetch `metadata/parquet/year=YYYY/metadata.parquet` for each year."""
    paths = []
    for year in years:
        dest = DATA_DIR / "metadata" / f"year={year}" / "metadata.parquet"
        _aws_s3_cp(f"metadata/parquet/year={year}/metadata.parquet", dest)
        paths.append(dest)
    return paths


def download_english_tar(year: int) -> tuple[Path, Path]:
    """Fetch the English judgment tar + its index for one year."""
    index_dest = DATA_DIR / "tar" / f"year={year}" / "english" / "english.index.json"
    tar_dest = DATA_DIR / "tar" / f"year={year}" / "english" / "english.tar"
    _aws_s3_cp(f"data/tar/year={year}/english/english.index.json", index_dest)
    _aws_s3_cp(f"data/tar/year={year}/english/english.tar", tar_dest)
    return index_dest, tar_dest


def download_english_tars(years: list[int]) -> list[tuple[Path, Path]]:
    """Fetch the English judgment tar + index for each year in `years`."""
    return [download_english_tar(year) for year in years]


def main() -> None:
    """`make data-sample` (default): SAMPLE_YEARS only. `--full`: config.FULL_YEARS —
    a multi-GB fetch the user triggers deliberately via `make db`, never via `make setup`.
    """
    import sys

    from pramaan.config import FULL_YEARS

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    years = FULL_YEARS if "--full" in sys.argv else SAMPLE_YEARS
    download_metadata(years)
    download_english_tars(years)


if __name__ == "__main__":
    main()
