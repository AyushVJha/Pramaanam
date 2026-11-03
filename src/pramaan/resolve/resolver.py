"""Resolve a citation to a case_id. (M3, SPEC.md section 4 step 3)

Order: exact neutral citation -> exact reporter (SCR) citation -> fuzzy party names + year.

SCC, AIR and SCC OnLine numbers are not in the open dataset, so those citations can only be
resolved by the fuzzy step (see docs/DATA_NOTES.md section 9).
"""

import sqlite3
from typing import Literal

from pydantic import BaseModel

from pramaan.citations.extract import Citation
from pramaan.citations.normalise import ParsedCitation
from pramaan.resolve.names import DECISION_YEAR_SQL, find_name_candidates


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
# Starting value only. It is tuned on the dev set and never on test (CLAUDE.md hard rule).
DEFAULT_THRESHOLD = 0.85
# If the runner-up scores within this of the winner, the name alone cannot tell them apart.
TIE_MARGIN = 0.02
_EXACT_METHOD = {"INSC": "neutral", "SCR": "reporter"}


def lookup_exact(con: sqlite3.Connection, parsed: ParsedCitation) -> list[Candidate]:
    """All cases whose stored citation equals this one. Empty for SCC/AIR/SCC OnLine."""
    if parsed.reporter not in _EXACT_METHOD:
        return []
    sql = (
        f"SELECT c.cnr, c.title, {DECISION_YEAR_SQL} FROM case_citations x "
        "JOIN cases c ON c.cnr = x.case_id "
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


def resolve_fuzzy(
    con: sqlite3.Connection, case_name: str | None, year: int | None, threshold: float,
    exclude_case: str | None = None,
) -> Resolution:
    """Match on party names, limited to decisions near `year` when a year is known."""
    if not case_name:
        return Resolution(case_id=None, method="none", confidence=0.0)
    found = find_name_candidates(
        con, case_name, year, limit=MAX_ALTERNATIVES, exclude_case=exclude_case
    )
    alternatives = [
        Candidate(case_id=c.case_id, title=c.title, year=c.year, score=c.score) for c in found
    ]
    if not found or found[0].score < threshold:
        return Resolution(
            case_id=None, method="none", confidence=found[0].score if found else 0.0,
            alternatives=alternatives,
        )
    # Cases within TIE_MARGIN of the best score are near-ties. The report year is usually the
    # decision year (84% of SCR citations, DATA_NOTES.md), so among near-ties prefer the one
    # decided closest to the cited year. Ambiguous only if that still does not separate them.
    top = [c for c in found if c.score >= found[0].score - TIE_MARGIN]

    def lag(c: Candidate) -> int:
        return year - c.year if year is not None else 0

    best_lag = min(lag(c) for c in top)
    closest = [c for c in top if lag(c) == best_lag]
    if len(closest) > 1:
        return Resolution(
            case_id=None, method="ambiguous", confidence=found[0].score, alternatives=alternatives
        )
    winner = closest[0]
    return Resolution(
        case_id=winner.case_id, method="fuzzy", confidence=winner.score, alternatives=alternatives
    )


def resolve(
    con: sqlite3.Connection, citation: Citation, threshold: float = DEFAULT_THRESHOLD,
    exclude_case: str | None = None,
) -> Resolution:
    """Exact neutral -> exact reporter -> fuzzy names + year. `exclude_case` is for benchmarks."""
    year = citation.parsed.year if citation.parsed else None
    if citation.parsed is not None:
        exact = resolve_exact(con, citation.parsed)
        if exact is not None:
            return exact
    return resolve_fuzzy(con, citation.case_name, year, threshold, exclude_case)
