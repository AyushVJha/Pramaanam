"""Has a later judgment overruled or disapproved this case? (G2)

Reads the `treatments` table (src/pramaan/data/build_treatments.py). Only the STRONG labels can
change a status, and only from VERIFIED to NEEDS_REVIEW: a person must decide whether the case is
still good law for the point cited. Soft labels (distinguished, followed, ...) are returned for
display only. A database built without the table simply has no treatments.
"""

import sqlite3

from pydantic import BaseModel

from pramaan.resolve.names import DECISION_YEAR_SQL

STRONG = ("overruled", "partly overruled", "disapproved", "held per incuriam")
SOFT = ("distinguished", "not followed", "doubted", "explained", "followed", "approved",
        "affirmed", "reversed")


class Treatment(BaseModel):
    label: str
    citing_case: str
    citing_title: str
    citing_year: int | None
    snippet: str

    @property
    def strong(self) -> bool:
        return self.label in STRONG


def treatments_of(con: sqlite3.Connection, case_id: str, limit: int = 5) -> list[Treatment]:
    """Treatments recorded for this case, strong ones first, then newest first."""
    try:
        rows = con.execute(
            f"SELECT t.label, t.citing_case, c.title, {DECISION_YEAR_SQL}, t.snippet "
            "FROM treatments t JOIN cases c ON c.cnr = t.citing_case WHERE t.cited_case = ?",
            (case_id,),
        ).fetchall()
    except sqlite3.OperationalError:  # no treatments table in this database
        return []
    found = [Treatment(label=r[0], citing_case=r[1], citing_title=r[2], citing_year=r[3],
                       snippet=r[4]) for r in rows]
    found.sort(key=lambda t: (not t.strong, -(t.citing_year or 0), t.citing_case))
    return found[:limit]


def adverse(treatments: list[Treatment]) -> list[Treatment]:
    return [t for t in treatments if t.strong]
