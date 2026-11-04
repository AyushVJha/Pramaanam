"""Copy the sample's PDFs out of the archived yearly tars. One tar at a time, deleted after use.

Why whole tars: reading a byte range from Google Drive costs ~30 s per call, and a tar has no
index of byte positions, so finding one file would take ~1000 calls.
Downloading the tar once is faster.

Reads bench/data/ground_truth/sample.json; writes PDFs to bench/data/ground_truth/pdfs/.
Skips PDFs already present, so it can be re-run after a stop.
Usage: uv run python scripts/fetch_sample_pdfs.py
"""

import json
import logging
import subprocess
import tarfile
import tempfile
from pathlib import Path

from pramaan.config import ARCHIVE_REMOTE, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("fetch_sample")
GT = DATA_DIR.parent / "bench" / "data" / "ground_truth"


def main() -> None:
    cases = json.loads((GT / "sample.json").read_text())["cases"]
    out = GT / "pdfs"
    out.mkdir(exist_ok=True)
    by_year: dict[int, list[str]] = {}
    for c in cases:
        if not (out / f"{c['path']}_EN.pdf").exists():
            by_year.setdefault(int(c["year"]), []).append(f"{c['path']}_EN.pdf")
    log.info("%d years to fetch, %d PDFs", len(by_year), sum(map(len, by_year.values())))
    for year, names in sorted(by_year.items()):
        with tempfile.TemporaryDirectory(dir=GT) as tmp:
            remote = f"{ARCHIVE_REMOTE}/raw/tar/year={year}/english/english.tar"
            log.info("year %d: downloading", year)
            subprocess.run(["rclone", "copy", remote.rsplit("/", 1)[0], tmp,
                            "--include", "english.tar"], check=True)
            with tarfile.open(Path(tmp) / "english.tar") as tar:
                for name in names:
                    fh = tar.extractfile(name)
                    if fh is None:
                        log.warning("missing in tar: %s", name)
                        continue
                    (out / name).write_bytes(fh.read())
            log.info("year %d: done, tar deleted", year)


if __name__ == "__main__":
    main()
