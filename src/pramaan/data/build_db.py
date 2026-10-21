"""Build the SQLite corpus DB: cases, case_citations, paragraphs, and FTS5 indices
(SPEC.md §3.4).

Idempotent: always rebuilds from scratch (drops and recreates tables, deterministic output
for the same input years) rather than trying to patch an existing DB incrementally.

Design notes from docs/DATA_NOTES.md / DECISIONS.md:
- `cases` is keyed on `cnr`, not the metadata's `case_id` (which is just the neutral
  citation reformatted, and empty for 4.7% of 2024 rows).
- `case_citations.case_id` is a foreign key to `cases.cnr` — the column name follows
  SPEC.md §3.4's schema sketch, but its value is the `cnr`, never the metadata's `case_id`.
"""

import logging
import sqlite3
import tarfile
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from pramaan.citations.normalise import parse_neutral, parse_scr
from pramaan.config import DATA_DIR, DB_PATH, SAMPLE_YEARS
from pramaan.data.paragraphs import Paragraph, split_paragraphs
from pramaan.data.pdf_text import extract_pages

logger = logging.getLogger(__name__)


class CaseCitation(BaseModel):
    case_id: str  # FK -> cases.cnr
    reporter: str
    year: int
    volume: int | None
    page: int
    raw: str


class BuildSummary(BaseModel):
    years: list[int]
    n_cases: int
    n_paragraphs: int
    pct_cases_zero_paragraphs: float
    pct_cases_with_neutral_citation: float


def parse_scr_citation(case_id: str, raw: str) -> CaseCitation | None:
    parsed = parse_scr(raw)
    if not parsed:
        return None
    return CaseCitation(case_id=case_id, raw=raw, **parsed.model_dump())


def parse_neutral_citation(case_id: str, raw: str) -> CaseCitation | None:
    parsed = parse_neutral(raw)
    if not parsed:
        return None
    return CaseCitation(case_id=case_id, raw=raw, **parsed.model_dump())


SCHEMA = """
DROP TABLE IF EXISTS cases;
DROP TABLE IF EXISTS case_citations;
DROP TABLE IF EXISTS paragraphs;
DROP TABLE IF EXISTS paragraphs_fts;
DROP TABLE IF EXISTS names_fts;

CREATE TABLE cases (
    cnr TEXT PRIMARY KEY,
    case_id TEXT,
    title TEXT,
    petitioner TEXT,
    respondent TEXT,
    decision_date TEXT,
    year INTEGER,
    judges TEXT,
    citation_raw TEXT,
    neutral_citation TEXT,
    pdf_path TEXT
);

CREATE TABLE case_citations (
    case_id TEXT NOT NULL REFERENCES cases(cnr),
    reporter TEXT NOT NULL,
    year INTEGER NOT NULL,
    volume INTEGER,
    page INTEGER NOT NULL,
    raw TEXT NOT NULL
);

CREATE TABLE paragraphs (
    case_id TEXT NOT NULL REFERENCES cases(cnr),
    para_no INTEGER NOT NULL,
    page INTEGER NOT NULL,
    text TEXT NOT NULL
);

CREATE VIRTUAL TABLE paragraphs_fts USING fts5(
    text, content='paragraphs', content_rowid='rowid'
);

CREATE VIRTUAL TABLE names_fts USING fts5(
    petitioner, respondent, content='cases', content_rowid='rowid', tokenize='trigram'
);
"""


def _pdf_filename(path: str) -> str:
    return f"{path}_EN.pdf"


def _load_tar_members(tar_path: Path) -> set[str] | None:
    if not tar_path.exists():
        return None
    with tarfile.open(tar_path) as tar:
        return {m.name for m in tar.getmembers() if m.isfile()}


def _case_paragraphs(
    tar_path: Path, pdf_filename: str, petitioner: str, respondent: str
) -> list[Paragraph]:
    with tarfile.open(tar_path) as tar:
        fh = tar.extractfile(pdf_filename)
        if fh is None:
            return []
        data = fh.read()
    try:
        return split_paragraphs(extract_pages(data, petitioner, respondent))
    except Exception:
        logger.warning("failed to extract/split %s", pdf_filename, exc_info=True)
        return []


def build(
    db_path: Path = DB_PATH, years: list[int] = SAMPLE_YEARS, data_dir: Path = DATA_DIR
) -> BuildSummary:
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    n_cases = 0
    n_paragraphs = 0
    n_zero_paragraph_cases = 0
    n_with_neutral_citation = 0

    for year in years:
        metadata_path = data_dir / "metadata" / f"year={year}" / "metadata.parquet"
        if not metadata_path.exists():
            logger.warning("no metadata for year=%s at %s, skipping", year, metadata_path)
            continue
        df = pd.read_parquet(metadata_path)

        tar_path = data_dir / "tar" / f"year={year}" / "english" / "english.tar"
        tar_members = _load_tar_members(tar_path)
        if tar_members is None:
            logger.warning(
                "no English tar for year=%s at %s; paragraphs will be empty", year, tar_path
            )

        for row in df.itertuples():
            cnr = row.cnr
            pdf_filename = _pdf_filename(row.path)
            has_pdf = tar_members is not None and pdf_filename in tar_members

            con.execute(
                "INSERT INTO cases (cnr, case_id, title, petitioner, respondent, decision_date, "
                "year, judges, citation_raw, neutral_citation, pdf_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cnr, row.case_id, row.title, row.petitioner, row.respondent,
                    row.decision_date, int(row.year), row.judge, row.citation,
                    row.nc_display, pdf_filename if has_pdf else None,
                ),
            )
            n_cases += 1

            scr = parse_scr_citation(cnr, row.citation)
            if scr:
                con.execute(
                    "INSERT INTO case_citations VALUES (?, ?, ?, ?, ?, ?)",
                    (scr.case_id, scr.reporter, scr.year, scr.volume, scr.page, scr.raw),
                )
            if isinstance(row.case_id, str) and row.case_id.strip():
                neutral = parse_neutral_citation(cnr, row.case_id)
                if neutral:
                    con.execute(
                        "INSERT INTO case_citations VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            neutral.case_id, neutral.reporter, neutral.year,
                            neutral.volume, neutral.page, neutral.raw,
                        ),
                    )
                    n_with_neutral_citation += 1

            paragraphs = (
                _case_paragraphs(tar_path, pdf_filename, row.petitioner, row.respondent)
                if has_pdf
                else []
            )
            if not paragraphs:
                n_zero_paragraph_cases += 1
            for para in paragraphs:
                con.execute(
                    "INSERT INTO paragraphs (case_id, para_no, page, text) VALUES (?, ?, ?, ?)",
                    (cnr, para.para_no, para.page, para.text),
                )
                n_paragraphs += 1

    con.execute("INSERT INTO paragraphs_fts(rowid, text) SELECT rowid, text FROM paragraphs")
    con.execute(
        "INSERT INTO names_fts(rowid, petitioner, respondent) "
        "SELECT rowid, petitioner, respondent FROM cases"
    )
    con.commit()
    con.close()

    return BuildSummary(
        years=years,
        n_cases=n_cases,
        n_paragraphs=n_paragraphs,
        pct_cases_zero_paragraphs=100.0 * n_zero_paragraph_cases / n_cases if n_cases else 0.0,
        pct_cases_with_neutral_citation=(
            100.0 * n_with_neutral_citation / n_cases if n_cases else 0.0
        ),
    )


def main() -> None:
    import sys

    from pramaan.config import FULL_YEARS

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    years = FULL_YEARS if "--full" in sys.argv else SAMPLE_YEARS
    summary = build(years=years)
    logger.info("years:                        %s", summary.years)
    logger.info("cases:                        %d", summary.n_cases)
    logger.info("paragraphs:                   %d", summary.n_paragraphs)
    logger.info("%% cases with zero paragraphs: %.1f%%", summary.pct_cases_zero_paragraphs)
    logger.info(
        "%% cases with neutral citation: %.1f%%", summary.pct_cases_with_neutral_citation
    )


if __name__ == "__main__":
    main()
