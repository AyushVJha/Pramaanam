"""Make sure the judgment database exists on a host that does not have it. (deploy)

The serving database is published as one gzip file with a known sha256. On first start the app
downloads it, checks the hash BEFORE unpacking, unpacks to a temporary name and renames it into
place, so a half-finished download can never be mistaken for a database.
"""

import gzip
import hashlib
import logging
import shutil
import tempfile
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)
CHUNK = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_database(db_path: Path, url: str | None, expected_sha256: str | None) -> bool:
    """True if db_path exists afterwards. Downloads and unpacks it when missing and a URL is set."""
    if db_path.exists():
        return True
    if not url or not expected_sha256:
        logger.warning("database %s missing; PRAMAAN_DB_URL / PRAMAAN_DB_SHA256 not set", db_path)
        return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=db_path.parent) as tmp:
        packed = Path(tmp) / "db.gz"
        logger.info("downloading database from %s", url)
        with urllib.request.urlopen(url, timeout=120) as response, packed.open("wb") as out:
            shutil.copyfileobj(response, out, CHUNK)
        if sha256_of(packed) != expected_sha256:
            raise RuntimeError("Downloaded database has the wrong sha256; not using it.")
        unpacked = Path(tmp) / "db"
        with gzip.open(packed, "rb") as src, unpacked.open("wb") as dst:
            shutil.copyfileobj(src, dst, CHUNK)
        unpacked.replace(db_path)  # same filesystem as db_path (tmp lives beside it): atomic
    logger.info("database ready at %s", db_path)
    return True
