"""Permanent archive of the raw bucket files on an rclone remote (e.g. Google Drive).

Raw files are copied once, verified, and recorded in a manifest. After that the local copy
can be deleted and restored later from the archive instead of re-downloading from S3.

Remote layout mirrors the bucket:  <remote>/raw/<same key as in the bucket>
Local layout (DATA_DIR) already uses the bucket's keys:
    metadata/year=Y/metadata.parquet   tar/year=Y/english/english.{tar,index.json}
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pramaan.config import ARCHIVE_REMOTE, DATA_DIR
from pramaan.data.retry import run_with_retry

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.jsonl"


def year_files(year: int) -> list[str]:
    """Paths (relative to DATA_DIR) of the raw files we keep for one year."""
    return [
        f"metadata/year={year}/metadata.parquet",
        f"tar/year={year}/english/english.index.json",
        f"tar/year={year}/english/english.tar",
    ]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archived_years(data_dir: Path = DATA_DIR) -> set[int]:
    """Years whose raw files were uploaded AND verified (recorded in the manifest)."""
    manifest = data_dir / MANIFEST_NAME
    if not manifest.exists():
        return set()
    return {json.loads(line)["year"] for line in manifest.read_text().splitlines() if line}


def _rclone(args: list[str], label: str) -> None:
    run_with_retry(["rclone", *args], label)


def archive_year(year: int, data_dir: Path = DATA_DIR, remote: str = ARCHIVE_REMOTE) -> None:
    """Upload one year's raw files, verify them against the remote, then record in manifest."""
    if year in archived_years(data_dir):
        return
    entries = []
    for rel in year_files(year):
        local = data_dir / rel
        dest = f"{remote}/raw/{rel}"
        _rclone(["copyto", str(local), dest], f"upload {rel}")
        # `check` compares size and hash on the remote side without downloading the file.
        _rclone(["check", str(local.parent), dest.rsplit("/", 1)[0], "--one-way",
                 "--include", local.name], f"verify {rel}")
        entries.append({
            "year": year,
            "file": rel,
            "size": local.stat().st_size,
            "sha256": sha256_file(local),
            "archived_at": datetime.now(UTC).isoformat(timespec="seconds"),
        })
    with (data_dir / MANIFEST_NAME).open("a") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
    _rclone(["copyto", str(data_dir / MANIFEST_NAME), f"{remote}/{MANIFEST_NAME}"],
            "upload manifest")


def restore_year(year: int, data_dir: Path = DATA_DIR, remote: str = ARCHIVE_REMOTE) -> None:
    """Copy one year's raw files back from the archive (skips files already present)."""
    for rel in year_files(year):
        local = data_dir / rel
        if local.exists():
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        _rclone(["copyto", f"{remote}/raw/{rel}", str(local)], f"restore {rel}")
