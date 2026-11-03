"""Party-name candidate lookup via names_fts trigram index + rapidfuzz rescoring. (M3)

Two steps, because each is good at one thing:
1. The FTS trigram index finds a few hundred cases that share a distinctive word with the draft
   (fast, but its ranking knows nothing about word order or which party is which).
2. rapidfuzz then scores petitioner against petitioner and respondent against respondent.
"""

import re
import sqlite3

from pydantic import BaseModel
from rapidfuzz import fuzz

from pramaan.citations.normalise import normalise_party_name

_SPLIT = re.compile(r"\s+(?:v\.?|vs\.?|versus|-vs-)\s+", re.IGNORECASE)
_MIN_WORD = 4  # shorter words ("of", "state") match far too many cases
_WORDS_PER_PARTY = 2
CANDIDATE_LIMIT = 200
YEARS_BEFORE = 2  # a report year can lag the decision year (measured on SCR, DATA_NOTES.md)


class NameCandidate(BaseModel):
    case_id: str
    title: str
    year: int
    score: float  # 0-1


def split_parties(case_name: str) -> tuple[str, str] | None:
    """'A v. B' -> ('A', 'B'). None when the name has no 'v.' to split on."""
    parts = _SPLIT.split(case_name.strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return None
    return parts[0].strip(), parts[1].strip()


def _distinctive_words(party: str) -> list[str]:
    words = {w for w in re.findall(r"[A-Z]+", normalise_party_name(party)) if len(w) >= _MIN_WORD}
    return sorted(words, key=len, reverse=True)[:_WORDS_PER_PARTY]


def fts_query(petitioner: str, respondent: str) -> str | None:
    words = _distinctive_words(petitioner) + _distinctive_words(respondent)
    if not words:
        return None
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


def party_similarity(a: str, b: str) -> float:
    """0-1 similarity of two party names after stripping '& Ors.', 'M/s' etc."""
    return fuzz.token_set_ratio(normalise_party_name(a), normalise_party_name(b)) / 100


def find_name_candidates(
    con: sqlite3.Connection, case_name: str, year: int | None, limit: int = 3
) -> list[NameCandidate]:
    """Best-matching cases for 'A v. B', best first. A year limits decisions to a window."""
    parties = split_parties(case_name)
    if parties is None:
        return []
    draft_pet, draft_resp = parties
    query = fts_query(draft_pet, draft_resp)
    if query is None:
        return []

    sql = (
        "SELECT c.cnr, c.title, c.year, c.petitioner, c.respondent FROM names_fts "
        "JOIN cases c ON c.rowid = names_fts.rowid WHERE names_fts MATCH ?"
    )
    args: list = [query]
    if year is not None:
        sql += " AND c.year BETWEEN ? AND ?"
        args += [year - YEARS_BEFORE, year]
    rows = con.execute(sql + " ORDER BY rank LIMIT ?", [*args, CANDIDATE_LIMIT]).fetchall()

    scored = []
    for cnr, title, y, pet, resp in rows:
        score = (
            party_similarity(draft_pet, pet or "") + party_similarity(draft_resp, resp or "")
        ) / 2
        scored.append(NameCandidate(case_id=cnr, title=title, year=y, score=score))
    scored.sort(key=lambda c: (-c.score, c.case_id))
    return scored[:limit]
