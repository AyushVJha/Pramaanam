"""Where layout blocks are kept: one folder per year, append-only (re-plan steps 4 and 6).

    <data>/layout/year=YYYY/blocks-<n>.parquet   rows: path + every Block field
    <data>/layout/year=YYYY/done.jsonl           one line per finished judgment

A judgment is finished only when its blocks file is fully written and its line is in done.jsonl,
in that order. A crash in between leaves an orphan blocks file that no done line points to; it is
ignored. Rebuilding is therefore safe to stop and restart: finished judgments are skipped.
The layer is never edited in place: a new engine version writes to a new folder name.
"""

import hashlib
import json
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from pramaan.config import DATA_DIR
from pramaan.data.layout import Block


class DoneRecord(BaseModel):
    path: str  # the judgment's file stem, as in the metadata `path` column
    pages: int
    blocks: int
    seconds: float
    engine: str
    pdf_sha256: str
    part: str  # name of the blocks file holding this judgment


def layout_dir(year: int, engine_name: str = "layout-v1", data_dir: Path = DATA_DIR) -> Path:
    return data_dir / engine_name / f"year={year}"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def finished(folder: Path) -> dict[str, DoneRecord]:
    """Judgments already stored, by path. Only lines whose blocks file really exists count."""
    done_file = folder / "done.jsonl"
    if not done_file.exists():
        return {}
    out = {}
    for line in done_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = DoneRecord(**json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue  # a half-written last line after a crash
        if (folder / rec.part).exists():
            out[rec.path] = rec
    return out


def write_batch(
    folder: Path, results: list[tuple[DoneRecord, list[Block]]], part_number: int
) -> None:
    """Write the blocks of several judgments to one file, then record each as finished."""
    if not results:
        return
    folder.mkdir(parents=True, exist_ok=True)
    part = f"blocks-{part_number:05d}.parquet"
    rows = [
        {"path": rec.path, **block.model_dump()} for rec, blocks in results for block in blocks
    ]
    frame = pd.DataFrame(rows, columns=["path", *Block.model_fields.keys()])
    tmp = folder / f"{part}.tmp"
    frame.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(folder / part)  # atomic: the file is whole or absent
    with open(folder / "done.jsonl", "a", encoding="utf-8") as fh:
        for rec, _ in results:
            fh.write(rec.model_copy(update={"part": part}).model_dump_json() + "\n")


def read_blocks(folder: Path, path: str) -> list[Block]:
    """All blocks of one judgment, in page and reading order. Empty if not stored."""
    rec = finished(folder).get(path)
    if rec is None:
        return []
    frame = pd.read_parquet(folder / rec.part)
    frame = frame[frame["path"] == path].sort_values(["page", "idx"])
    return [Block(**row) for row in frame.drop(columns=["path"]).to_dict("records")]
