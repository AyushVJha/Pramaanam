"""Identity check: does the resolved case match the name and year the draft gave? (M3, SPEC 4.4)

Catches "right citation number, wrong case name" (the number points to some other case), which
is a common way for a model to get a citation subtly wrong.
"""

import sqlite3
from typing import Literal

from pydantic import BaseModel

from pramaan.resolve.names import DECISION_YEAR_SQL, party_similarity, split_parties

# Starting value only. Tuned on the dev set and never on test (CLAUDE.md hard rule).
NAME_MATCH_THRESHOLD = 0.7
# Each party must fit at least this well for a full "match". The average alone lets
# "Raja Ram v. Union of India" pass for "Bhule Ram v. Union of India" (DATA_NOTES 23).
# Chosen on dev (resolve_dev gold cases), never on test.
PARTY_MIN = 0.6
# A report year can be up to this many years after the decision year (DATA_NOTES.md).
MAX_REPORT_LAG = 2


class IdentityResult(BaseModel):
    verdict: Literal["match", "name_mismatch", "name_partial", "year_mismatch", "cannot_check"]
    name_score: float | None
    explanation: str


def party_scores(draft_name: str, petitioner: str, respondent: str) -> tuple[float, float] | None:
    """Similarity of each side of 'A v. B' to the stored parties. None if no 'v.' in the draft."""
    parties = split_parties(draft_name)
    if parties is None:
        return None
    return party_similarity(parties[0], petitioner), party_similarity(parties[1], respondent)


def name_score(draft_name: str, petitioner: str, respondent: str) -> float | None:
    """0-1 average similarity of 'A v. B' against the stored parties. None without a 'v.'."""
    both = party_scores(draft_name, petitioner, respondent)
    return None if both is None else (both[0] + both[1]) / 2


def compare_identity(
    draft_name: str | None,
    draft_year: int | None,
    petitioner: str,
    respondent: str,
    decision_year: int,
    threshold: float = NAME_MATCH_THRESHOLD,
) -> IdentityResult:
    """Pure comparison. Year is judged only when the name matched, so the reason is clear."""
    score = name_score(draft_name, petitioner, respondent) if draft_name else None
    if score is not None and score < threshold:
        return IdentityResult(
            verdict="name_mismatch", name_score=score,
            explanation=(
                f"The citation points to '{petitioner} v. {respondent}', "
                f"not '{draft_name}' (name similarity {score:.2f})."
            ),
        )
    both = party_scores(draft_name, petitioner, respondent) if draft_name else None
    if both is not None and min(both) < PARTY_MIN:
        return IdentityResult(
            verdict="name_partial", name_score=score,
            explanation=(
                f"Only one party of '{draft_name}' fits '{petitioner} v. {respondent}' "
                f"(scores {both[0]:.2f} and {both[1]:.2f}); check the name."
            ),
        )
    latest_ok = decision_year + MAX_REPORT_LAG
    if draft_year is not None and not (decision_year <= draft_year <= latest_ok):
        return IdentityResult(
            verdict="year_mismatch", name_score=score,
            explanation=(
                f"The draft gives {draft_year}, but that case was decided in {decision_year}."
            ),
        )
    if score is None and draft_year is None:
        return IdentityResult(
            verdict="cannot_check", name_score=None,
            explanation="The draft gives neither a case name with 'v.' nor a year to compare.",
        )
    return IdentityResult(verdict="match", name_score=score, explanation="Name and year agree.")


def check_identity(
    con: sqlite3.Connection, case_id: str, draft_name: str | None, draft_year: int | None,
    threshold: float = NAME_MATCH_THRESHOLD,
) -> IdentityResult:
    petitioner, respondent, year = con.execute(
        f"SELECT petitioner, respondent, {DECISION_YEAR_SQL} FROM cases c WHERE c.cnr = ?",
        (case_id,),
    ).fetchone()
    return compare_identity(
        draft_name, draft_year, petitioner or "", respondent or "", year, threshold
    )
