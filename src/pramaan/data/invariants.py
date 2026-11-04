"""Things that must always be true of the built database, and a manifest that pins its contents.

Each invariant is a SQL query that counts violations. `hard` ones must be 0 or the database is
broken; `soft` ones are reported numbers (known gaps in the source, DATA_NOTES 15) that we watch so
a rebuild cannot change them unnoticed.
"""

import hashlib
import sqlite3
from pathlib import Path

from pydantic import BaseModel

CHECKS: list[tuple[str, str, str]] = [
    # (name, kind, SQL returning one number)
    ("paragraph_without_case", "hard",
     "SELECT COUNT(*) FROM paragraphs p LEFT JOIN cases c ON c.cnr = p.case_id "
     "WHERE c.cnr IS NULL"),
    ("citation_without_case", "hard",
     "SELECT COUNT(*) FROM case_citations x LEFT JOIN cases c ON c.cnr = x.case_id "
     "WHERE c.cnr IS NULL"),
    ("alias_without_case", "hard",
     "SELECT COUNT(*) FROM citation_aliases a LEFT JOIN cases c ON c.cnr = a.case_id "
     "WHERE c.cnr IS NULL"),
    ("alias_citing_case_unknown", "hard",
     "SELECT COUNT(*) FROM citation_aliases a LEFT JOIN cases c ON c.cnr = a.citing_case "
     "WHERE c.cnr IS NULL"),
    ("alias_points_at_citing_case", "hard",
     "SELECT COUNT(*) FROM citation_aliases WHERE case_id = citing_case"),
    ("empty_paragraph", "hard", "SELECT COUNT(*) FROM paragraphs WHERE TRIM(text) = ''"),
    ("paragraph_page_below_1", "hard", "SELECT COUNT(*) FROM paragraphs WHERE page < 1"),
    ("case_without_title", "hard",
     "SELECT COUNT(*) FROM cases WHERE title IS NULL OR TRIM(title) = ''"),
    ("paragraphs_but_no_pdf_path", "hard",
     "SELECT COUNT(*) FROM cases c WHERE (c.pdf_path IS NULL OR c.pdf_path = '') "
     "AND EXISTS (SELECT 1 FROM paragraphs p WHERE p.case_id = c.cnr)"),
    ("case_without_pdf_path", "soft",
     "SELECT COUNT(*) FROM cases WHERE pdf_path IS NULL OR pdf_path = ''"),
    ("unknown_reporter", "hard",
     "SELECT COUNT(*) FROM case_citations WHERE reporter NOT IN ('INSC', 'SCR', 'SCR-SUPP')"),
    ("case_without_paragraphs", "soft",
     "SELECT COUNT(*) FROM cases c WHERE NOT EXISTS "
     "(SELECT 1 FROM paragraphs p WHERE p.case_id = c.cnr)"),
    ("case_without_any_citation", "soft",
     "SELECT COUNT(*) FROM cases c WHERE NOT EXISTS "
     "(SELECT 1 FROM case_citations x WHERE x.case_id = c.cnr)"),
    ("cases_with_thin_text", "soft",
     "SELECT COUNT(*) FROM (SELECT 1 FROM paragraphs GROUP BY case_id "
     "HAVING MAX(page) >= 3 AND SUM(LENGTH(text)) * 1.0 / MAX(page) < 800)"),
    ("duplicate_paragraph_numbers", "soft",
     "SELECT COUNT(*) FROM "
     "(SELECT 1 FROM paragraphs GROUP BY case_id, para_no HAVING COUNT(*) > 1)"),
]


class InvariantResult(BaseModel):
    name: str
    kind: str
    violations: int

    @property
    def ok(self) -> bool:
        return self.kind == "soft" or self.violations == 0


def run_invariants(con: sqlite3.Connection) -> list[InvariantResult]:
    return [
        InvariantResult(name=n, kind=k, violations=con.execute(sql).fetchone()[0])
        for n, k, sql in CHECKS
    ]


class Manifest(BaseModel):
    sha256: str
    bytes: int
    tables: dict[str, int]
    soft_counts: dict[str, int]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 24):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(db_path: Path, con: sqlite3.Connection) -> Manifest:
    tables = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("cases", "paragraphs", "case_citations", "citation_aliases")
    }
    soft = {r.name: r.violations for r in run_invariants(con) if r.kind == "soft"}
    return Manifest(
        sha256=sha256_file(db_path), bytes=db_path.stat().st_size, tables=tables, soft_counts=soft
    )
