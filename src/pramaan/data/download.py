"""Download metadata parquet and judgment tars from the public `indian-supreme-court-judgments`
S3 bucket (CC-BY-4.0, no AWS credentials needed — see SPEC.md §3.1).

M0 scope: metadata for a few years, plus the English tar for one year, so we can inspect the
data before designing the resolver. `make db` / full-range downloads come in M1.
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

BUCKET = "indian-supreme-court-judgments"
REGION = "ap-south-1"
DATA_DIR = Path("data")

METADATA_YEARS = [2022, 2023, 2024]
TAR_YEAR = 2023


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
    subprocess.run(
        [
            "aws", "s3", "cp", url, str(dest),
            "--no-sign-request", "--region", REGION,
        ],
        check=True,
    )


def download_metadata(years: list[int] = METADATA_YEARS) -> list[Path]:
    """Fetch `metadata/parquet/year=YYYY/metadata.parquet` for each year."""
    paths = []
    for year in years:
        dest = DATA_DIR / "metadata" / f"year={year}" / "metadata.parquet"
        _aws_s3_cp(f"metadata/parquet/year={year}/metadata.parquet", dest)
        paths.append(dest)
    return paths


def download_english_tar(year: int = TAR_YEAR) -> tuple[Path, Path]:
    """Fetch the English judgment tar + its index for one year."""
    index_dest = DATA_DIR / "tar" / f"year={year}" / "english" / "english.index.json"
    tar_dest = DATA_DIR / "tar" / f"year={year}" / "english" / "english.tar"
    _aws_s3_cp(f"data/tar/year={year}/english/english.index.json", index_dest)
    _aws_s3_cp(f"data/tar/year={year}/english/english.tar", tar_dest)
    return index_dest, tar_dest


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    download_metadata()
    download_english_tar()


if __name__ == "__main__":
    main()
