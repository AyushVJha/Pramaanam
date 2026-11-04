"""Build the SCC / AIR -> case alias table from parallel citations inside judgments.

The open dataset has no SCC or AIR numbers, but judgments print them next to the numbers it does
have: "Name, (2001) 2 SCC 386 : [2001] 1 SCR 1". The SCR (or neutral) number finds the case by
exact lookup, so the SCC / AIR number written beside it names the same case.

One row is stored per piece of evidence, with the judgment that printed it (`citing_case`). The
resolver counts rows at lookup time, and a benchmark can leave out the judgment under test.
Measured on held-out judgments (docs/DATA_NOTES.md section 13): 99% of answers right.

Usage: uv run python -m pramaan.data.build_aliases [path/to/pramaan.db]
"""

import logging
import sqlite3
import sys

from pramaan.citations.extract import Citation, extract
from pramaan.resolve.resolver import lookup_exact

logger = logging.getLogger(__name__)

ALIAS_FORMATS = {"SCC", "AIR"}  # SCC OnLine uses a separate per-year numbering: not mapped
ANCHOR_FORMATS = {"SCR", "NEUTRAL"}  # the numbers the dataset can look up exactly
MAX_YEAR_GAP = 2  # parallel numbers of one case are within a couple of years of each other

ALIASES_SCHEMA = """
DROP TABLE IF EXISTS citation_aliases;
CREATE TABLE citation_aliases (
    reporter TEXT NOT NULL,      -- 'SCC' or 'AIR'
    year INTEGER NOT NULL,
    volume INTEGER,              -- NULL for AIR
    page INTEGER NOT NULL,
    case_id TEXT NOT NULL REFERENCES cases(cnr),
    citing_case TEXT NOT NULL    -- the judgment that printed the pair
);
CREATE INDEX idx_aliases_lookup ON citation_aliases(reporter, year, volume, page);
"""


def citation_groups(text: str, cits: list[Citation]) -> list[list[Citation]]:
    """Citations separated only by whitespace or a colon belong to one case ('SCC : AIR : SCR')."""
    groups: list[list[Citation]] = []
    for c in sorted((c for c in cits if c.format != "CASE_NAME"), key=lambda c: c.span):
        if groups and text[groups[-1][-1].span[1] : c.span[0]].strip(" \t\n:") == "":
            groups[-1].append(c)
        else:
            groups.append([c])
    return groups


def aliases_in_text(
    con: sqlite3.Connection, citing_case: str, text: str
) -> list[tuple[str, int, int | None, int, str, str]]:
    """Rows (reporter, year, volume, page, case_id, citing_case) found in one paragraph."""
    rows = []
    for group in citation_groups(text, extract(text)):
        anchors = [c for c in group if c.format in ANCHOR_FORMATS and c.parsed]
        aliases = [c for c in group if c.format in ALIAS_FORMATS and c.parsed]
        if len(anchors) != 1 or not aliases:
            continue  # two anchors would be two different cases in one chain: skip, do not guess
        hits = lookup_exact(con, anchors[0].parsed)
        if len(hits) != 1 or hits[0].case_id == citing_case:
            continue  # unknown or ambiguous anchor; or the judgment citing itself
        for a in aliases:
            p = a.parsed
            if abs(p.year - anchors[0].parsed.year) <= MAX_YEAR_GAP:
                rows.append((p.reporter, p.year, p.volume, p.page, hits[0].case_id, citing_case))
    return rows


def build_aliases(con: sqlite3.Connection) -> int:
    """(Re)create and fill citation_aliases. Returns the number of evidence rows stored."""
    con.executescript(ALIASES_SCHEMA)
    cases = [r[0] for r in con.execute("SELECT cnr FROM cases ORDER BY cnr")]
    n_rows = 0
    for i, cnr in enumerate(cases):
        paragraphs = con.execute("SELECT text FROM paragraphs WHERE case_id = ?", (cnr,)).fetchall()
        for (text,) in paragraphs:
            if "SCC" not in text and "AIR" not in text:
                continue  # cheap filter: most paragraphs hold no such citation
            rows = aliases_in_text(con, cnr, text)
            con.executemany("INSERT INTO citation_aliases VALUES (?, ?, ?, ?, ?, ?)", rows)
            n_rows += len(rows)
        if i % 5000 == 0:
            logger.info("aliases: %d/%d cases, %d rows", i, len(cases), n_rows)
    con.commit()
    return n_rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = sys.argv[1] if len(sys.argv) > 1 else "pramaan.db"
    connection = sqlite3.connect(db)
    logger.info("stored %d alias evidence rows", build_aliases(connection))
