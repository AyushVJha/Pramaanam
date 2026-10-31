"""Ingest corpus years: download once -> archive to Drive -> build the text layer.

Safe to stop and restart at any point (laptop shut, internet down, crash): each step checks
what already exists and skips it. Progress is therefore never stored in a separate state
file that could disagree with reality; it is read from the files themselves:
    raw files local?  -> data/<key>        archived+verified? -> data/manifest.jsonl
    text layer built? -> data/text/year=Y/pages.parquet

Usage:  python -m pramaan.data.ingest --years 2023
        python -m pramaan.data.ingest --full --free-raw      (what the background service runs)
        python -m pramaan.data.ingest --status
"""

import argparse
import logging
import shutil
import sys

from pramaan.config import DATA_DIR, FULL_YEARS
from pramaan.data.archive import archive_year, archived_years, restore_year, year_files
from pramaan.data.download import download_english_tar, download_metadata
from pramaan.data.text_layer import build_text_layer, text_layer_path

logger = logging.getLogger(__name__)

# Never let the disk fill up: stop (and let the service retry later) below this much free space.
MIN_FREE_BYTES = 4 * 1024**3


def _raw_present(year: int) -> bool:
    return all((DATA_DIR / rel).exists() for rel in year_files(year))


def ingest_year(year: int, free_raw: bool = False) -> None:
    """Bring one year to the finished state. Each step is skipped if already done."""
    archived = year in archived_years(DATA_DIR)
    parquet = text_layer_path(year)
    # The raw files are only needed to archive them or to build the text layer. A finished
    # year with its tar already freed must not trigger a pointless restore.
    needs_raw = not archived or not parquet.exists()
    if needs_raw and not _raw_present(year):
        free = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else ".").free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f"only {free / 1024**3:.1f} GiB free; need {MIN_FREE_BYTES >> 30}")
        if archived:
            logger.info("%s: restoring raw files from the archive", year)
            restore_year(year)
        else:
            logger.info("%s: downloading from the public bucket", year)
            download_metadata([year])
            download_english_tar(year)

    if not archived:
        logger.info("%s: archiving + verifying", year)
        archive_year(year)

    if not parquet.exists():
        logger.info("%s: building the text layer", year)
        n = build_text_layer(DATA_DIR / f"tar/year={year}/english/english.tar", parquet)
        logger.info("%s: text layer built from %d PDFs", year, n)

    if free_raw:
        # Only reachable once the archive entry (verified) and the text layer both exist.
        tar = DATA_DIR / f"tar/year={year}/english/english.tar"
        if tar.exists() and year in archived_years(DATA_DIR) and parquet.exists():
            tar.unlink()
            logger.info("%s: freed local raw tar (kept in the archive)", year)


def status(years: list[int]) -> None:
    done = archived_years(DATA_DIR)
    print("year  archived  text-layer")
    for y in years:
        has_text = text_layer_path(y).exists()
        print(f"{y}  {'yes' if y in done else 'no':8}  {'yes' if has_text else 'no'}")
    n_done = sum(1 for y in years if y in done and text_layer_path(y).exists())
    print(f"{n_done}/{len(years)} years complete")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, nargs="*")
    parser.add_argument("--full", action="store_true", help="all years in config.FULL_YEARS")
    parser.add_argument("--free-raw", action="store_true", help="delete local tar once archived")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    years = FULL_YEARS if args.full else (args.years or [])
    if args.status:
        status(years or FULL_YEARS)
        return
    if not years:
        parser.error("give --years Y [Y...] or --full")
    # Newest first: recent judgments matter most if we are ever interrupted for good.
    for year in sorted(years, reverse=True):
        ingest_year(year, free_raw=args.free_raw)
    logger.info("all requested years complete")
    sys.exit(0)


if __name__ == "__main__":
    main()
