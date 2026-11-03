"""Resolve a citation to a case_id. (M3, SPEC.md section 4 step 3)

Order: exact neutral citation -> exact reporter (SCR) citation -> fuzzy party names + year.

SCC, AIR and SCC OnLine numbers are not in the open dataset, so those citations can only be
resolved by the fuzzy step (see docs/DATA_NOTES.md section 9).
"""

import sqlite3
from typing import Literal

from pydantic import BaseModel

from pramaan.citations.normalise import ParsedCitation


class Candidate(BaseModel):
    case_id: str
    title: str
    year: int
    score: float  # 1.0 for an exact match, a 0-1 similarity for a fuzzy one


class Resolution(BaseModel):
    case_id: str | None
    # "ambiguous": the number matched more than one case, so we refuse to pick one.
    method: Literal["neutral", "reporter", "fuzzy", "ambiguous", "none"]
    confidence: float
    alternatives: list[Candidate] = []  # up to 3, best first


MAX_ALTERNATIVES = 3
_EXACT_METHOD = {"INSC": "neutral", "SCR": "reporter"}


def lookup_exact(con: sqlite3.Connection, parsed: ParsedCitation) -> list[Candidate]:
    """All cases whose stored citation equals this one. Empty for SCC/AIR/SCC OnLine."""
    if parsed.reporter not in _EXACT_METHOD:
        return []
    sql = (
        "SELECT c.cnr, c.title, c.year FROM case_citations x JOIN cases c ON c.cnr = x.case_id "
        "WHERE x.reporter = ? AND x.year = ? AND x.page = ?"
    )
    args: list = [parsed.reporter, parsed.year, parsed.page]
    if parsed.volume is not None:  # a draft may leave the volume out: "[1950] SCR 88"
        sql += " AND x.volume = ?"
        args.append(parsed.volume)
    rows = con.execute(sql + " ORDER BY c.cnr", args).fetchall()
    return [Candidate(case_id=r[0], title=r[1], year=r[2], score=1.0) for r in rows]


def resolve_exact(con: sqlite3.Connection, parsed: ParsedCitation) -> Resolution | None:
    """An exact-number resolution, or None when the number is not in the corpus at all."""
    hits = lookup_exact(con, parsed)
    if not hits:
        return None
    if len(hits) == 1:
        return Resolution(
            case_id=hits[0].case_id, method=_EXACT_METHOD[parsed.reporter], confidence=1.0
        )
    # A few neutral numbers were given to several cases in the source data. Do not guess.
    return Resolution(
        case_id=None, method="ambiguous", confidence=0.0, alternatives=hits[:MAX_ALTERNATIVES]
    )
