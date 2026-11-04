"""Resolve a citation to a case_id. (M3, SPEC.md section 4 step 3)

Order: exact neutral -> exact reporter (SCR) -> alias (SCC / AIR numbers learned from parallel
citations printed in judgments) -> fuzzy party names + year.

SCC, AIR and SCC OnLine numbers are not in the open dataset (docs/DATA_NOTES.md section 9). The
alias step recovers some SCC / AIR numbers; everything else goes to the fuzzy step.
"""

import sqlite3
from typing import Literal

from pydantic import BaseModel

from pramaan.checks.identity import NAME_MATCH_THRESHOLD, name_score
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
    method: Literal["neutral", "reporter", "alias", "fuzzy", "ambiguous", "none"]
    confidence: float
    alternatives: list[Candidate] = []  # up to 3, best first
    # For alias answers: how many OTHER judgments print this exact parallel-citation pair.
    witnesses: int | None = None


MAX_ALTERNATIVES = 3
# Starting value only. It is tuned on the dev set and never on test (CLAUDE.md hard rule).
DEFAULT_THRESHOLD = 0.85
# If the runner-up scores within this of the winner, the name alone cannot tell them apart.
TIE_MARGIN = 0.02
_EXACT_METHOD = {"INSC": "neutral", "SCR": "reporter", "SCR-SUPP": "reporter"}
# Measured on held-out judgments: 99.0% of alias answers were right (DATA_NOTES.md section 13).
ALIAS_CONFIDENCE = 0.99


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


NAME_PICK_MARGIN = 0.15  # starting value; checked on the shared-number cases, not tuned on test


def _only_name_match(
    con: sqlite3.Connection, hits: list[Candidate], case_name: str | None
) -> Candidate | None:
    """The candidate whose parties clearly fit the draft's name best, else None.

    "Clearly" = it passes the identity threshold and beats every other candidate by
    NAME_PICK_MARGIN. (The average over two parties is generous when one side is "Union of
    India" for both, so a bare threshold would not separate Bhule Ram from Raja Ram.)"""
    if not case_name:
        return None
    scored = []
    for hit in hits:
        row = con.execute(
            "SELECT petitioner, respondent FROM cases WHERE cnr = ?", (hit.case_id,)
        ).fetchone()
        score = name_score(case_name, row[0] or "", row[1] or "")
        if score is not None:
            scored.append((score, hit))
    scored.sort(key=lambda t: -t[0])
    if not scored or scored[0][0] < NAME_MATCH_THRESHOLD:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < NAME_PICK_MARGIN:
        return None
    return scored[0][1]


def resolve_exact(
    con: sqlite3.Connection, parsed: ParsedCitation, case_name: str | None = None
) -> Resolution | None:
    """An exact-number resolution, or None when the number is not in the corpus at all.

    When the source gave one number to several judgments, the draft's own case name may pick
    exactly one of them (number and name together); otherwise it stays ambiguous."""
    hits = lookup_exact(con, parsed)
    if not hits:
        return None
    if len(hits) == 1:
        return Resolution(
            case_id=hits[0].case_id, method=_EXACT_METHOD[parsed.reporter], confidence=1.0
        )
    # A few neutral numbers were given to several cases in the source data. Do not guess,
    # unless the draft's name fits exactly one of them.
    chosen = _only_name_match(con, hits, case_name)
    if chosen is not None:
        return Resolution(
            case_id=chosen.case_id, method=_EXACT_METHOD[parsed.reporter], confidence=1.0,
            alternatives=hits[:MAX_ALTERNATIVES],
        )
    return Resolution(
        case_id=None, method="ambiguous", confidence=0.0, alternatives=hits[:MAX_ALTERNATIVES]
    )


def resolve_alias(
    con: sqlite3.Connection, parsed: ParsedCitation, exclude_citing: str | None = None
) -> Resolution | None:
    """Look an SCC / AIR number up in the alias table. None if unknown, or if the evidence
    names more than one case (then we do not guess; the fuzzy step takes over).

    `exclude_citing` hides the evidence printed by one judgment, so a benchmark built from that
    judgment cannot be answered from its own text.
    """
    if parsed.reporter not in ("SCC", "AIR"):
        return None
    try:
        rows = con.execute(
            "SELECT DISTINCT case_id FROM citation_aliases "
            "WHERE reporter = ? AND year = ? AND volume IS ? AND page = ? AND citing_case != ?",
            (parsed.reporter, parsed.year, parsed.volume, parsed.page, exclude_citing or ""),
        ).fetchall()
    except sqlite3.OperationalError:
        return None  # an older database without the alias table
    if len(rows) != 1:
        return None
    witnesses = con.execute(
        "SELECT COUNT(DISTINCT citing_case) FROM citation_aliases "
        "WHERE reporter = ? AND year = ? AND volume IS ? AND page = ? AND case_id = ? "
        "AND citing_case != ?",
        (parsed.reporter, parsed.year, parsed.volume, parsed.page, rows[0][0],
         exclude_citing or ""),
    ).fetchone()[0]
    return Resolution(
        case_id=rows[0][0], method="alias", confidence=ALIAS_CONFIDENCE, witnesses=witnesses
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
    exclude_case: str | None = None, exclude_citing: str | None = None,
) -> Resolution:
    """Exact -> alias -> fuzzy. `exclude_case` and `exclude_citing` are for benchmarks only."""
    year = citation.parsed.year if citation.parsed else None
    if citation.parsed is not None:
        exact = resolve_exact(con, citation.parsed, citation.case_name)
        if exact is not None:
            return exact
        alias = resolve_alias(con, citation.parsed, exclude_citing)
        if alias is not None and alias.case_id != exclude_case:
            return alias
    return resolve_fuzzy(con, citation.case_name, year, threshold, exclude_case)
