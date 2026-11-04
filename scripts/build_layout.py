"""Build the layout layer (blocks per page) for whole years of judgments. Resumable.

For each year: copy that year's tar from the archive (rclone) to a temporary folder, convert every
judgment not yet finished with Docling + OCR in parallel worker processes, write the blocks, delete
the temporary files. Safe to stop (Ctrl-C) and restart: finished judgments are skipped
(see pramaan/data/layout_store.py).

Needs `uv sync --extra layout`, tesseract on PATH, and the rclone remote used by the archive.
Usage: uv run python scripts/build_layout.py --years 2024 2023 --workers 4
       uv run python scripts/build_layout.py --years 1990 --paths 1990_1_832_835 --workers 1
"""

import argparse
import json
import logging
import multiprocessing as mp
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from pramaan.config import ARCHIVE_REMOTE, DATA_DIR
from pramaan.data.layout import Block, convert_pdf, engine_version, make_converter
from pramaan.data.layout_store import DoneRecord, finished, layout_dir, sha256_of, write_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("build_layout")
BATCH = 40  # judgments per blocks file
_converter = None


def _init_worker(threads: int) -> None:
    global _converter
    _converter = make_converter(num_threads=threads)


def _convert(job: tuple[str, str]) -> tuple[str, list[Block] | None, float, str, str]:
    """Runs in a worker process. Returns (path, blocks or None, seconds, sha256, error)."""
    path, pdf = job
    start = time.time()
    try:
        blocks = convert_pdf(_converter, pdf)
        return path, blocks, time.time() - start, sha256_of(Path(pdf).read_bytes()), ""
    except Exception as exc:  # one bad PDF must not stop the year
        return path, None, time.time() - start, "", f"{type(exc).__name__}: {exc}"


def fetch_tar(year: int, folder: Path) -> Path:
    remote = f"{ARCHIVE_REMOTE}/raw/tar/year={year}/english"
    subprocess.run(
        ["rclone", "copy", remote, str(folder), "--include", "english.tar"], check=True
    )
    return folder / "english.tar"


def build_year(
    year: int, workers: int, engine_name: str, only: set[str] | None, limit: int
) -> None:
    out = layout_dir(year, engine_name)
    done = finished(out)
    tmp = DATA_DIR / "tmp_layout" / f"year={year}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        tar_path = fetch_tar(year, tmp)
        jobs = []
        with tarfile.open(tar_path) as tar:
            for member in tar:
                if not (member.isfile() and member.name.endswith("_EN.pdf")):
                    continue
                path = member.name.removesuffix("_EN.pdf")
                if path in done or (only is not None and path not in only):
                    continue
                target = tmp / member.name
                target.write_bytes(tar.extractfile(member).read())
                jobs.append((path, str(target)))
                if limit and len(jobs) >= limit:
                    break
        log.info("year %d: %d judgments to convert (%d already done)", year, len(jobs), len(done))
        engine = engine_version()
        part = len(list(out.glob("blocks-*.parquet"))) if out.exists() else 0
        pending: list[tuple[DoneRecord, list[Block]]] = []
        failed = []
        started = time.time()
        pages_done = 0
        ctx = mp.get_context("spawn")
        pool_args = {"initializer": _init_worker, "initargs": (2,), "maxtasksperchild": 40}
        with ctx.Pool(workers, **pool_args) as pool:
            for i, (path, blocks, secs, digest, err) in enumerate(
                pool.imap_unordered(_convert, jobs), start=1
            ):
                if blocks is None:
                    failed.append({"path": path, "error": err})
                    log.warning("FAILED %s: %s", path, err)
                    continue
                pages = max((b.page for b in blocks), default=0)
                pages_done += pages
                rec = DoneRecord(path=path, pages=pages, blocks=len(blocks), seconds=round(secs, 1),
                                 engine=engine, pdf_sha256=digest, part="")
                pending.append((rec, blocks))
                if len(pending) >= BATCH:
                    write_batch(out, pending, part)
                    part, pending = part + 1, []
                if i % 20 == 0:
                    rate = pages_done / (time.time() - started)
                    log.info("year %d: %d/%d judgments, %.1f pages/s", year, i, len(jobs), rate)
        write_batch(out, pending, part)
        if failed:
            out.mkdir(parents=True, exist_ok=True)
            with open(out / "failed.jsonl", "a", encoding="utf-8") as fh:
                for row in failed:
                    fh.write(json.dumps(row) + "\n")
        log.info("year %d finished: %d ok, %d failed", year, len(jobs) - len(failed), len(failed))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--engine-name", default="layout-v1")
    ap.add_argument("--paths", nargs="*", help="only these judgments (file stems)")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many (testing)")
    args = ap.parse_args()
    only = set(args.paths) if args.paths else None
    for year in args.years:
        build_year(year, args.workers, args.engine_name, only, args.limit)


if __name__ == "__main__":
    main()
