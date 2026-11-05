"""The locator agent: suggest candidates for a citation that did not resolve. (A4)

It is a helper for a person, not a judge. Its suggestions can turn NOT_FOUND_IN_CORPUS into
NEEDS_REVIEW with "possible match" lines. They can never produce VERIFIED (agents/guard.py).
A suggested id must have been shown to the model by a search tool, so it cannot invent one.
"""

import sqlite3

from pydantic import BaseModel

from pramaan.agents.runtime import AgentOutcome, Budget, run_agent
from pramaan.agents.tools import CaseFinder
from pramaan.llm.client import Backend
from pramaan.llm.prompts import LOCATOR_SYSTEM
from pramaan.resolve.names import DECISION_YEAR_SQL

MAX_SUGGESTIONS = 3


class Suggestion(BaseModel):
    case_id: str
    title: str
    year: int | None
    note: str = ""


class LocatorAnswer(BaseModel):
    case_ids: list[str] = []
    reason: str = ""


class LocatorResult(BaseModel):
    suggestions: list[Suggestion] = []
    reason: str = ""
    steps: int = 0
    cost_usd: float = 0.0
    failure: str | None = None
    trace: list[dict] = []


def locate(
    con: sqlite3.Connection,
    *,
    raw: str,
    case_name: str | None,
    context: str,
    budget: Budget | None = None,
    model: str | None = None,
    backend: Backend | None = None,
    **client_kw,
) -> LocatorResult:
    finder = CaseFinder(con)

    def verify(answer: BaseModel) -> str | None:
        assert isinstance(answer, LocatorAnswer)
        if len(answer.case_ids) > MAX_SUGGESTIONS:
            return f"at most {MAX_SUGGESTIONS} case ids"
        for cid in answer.case_ids:
            if cid not in finder.seen:
                return f"case id {cid} was never shown by a tool; only list ids you were shown"
        return None

    task = (
        f"CITATION AS WRITTEN: {raw}\nCASE NAME IN DRAFT: {case_name or '(none)'}\n"
        f"SENTENCE AROUND IT: {context[:600]}"
    )
    out: AgentOutcome = run_agent(
        task, system=LOCATOR_SYSTEM, tools=finder.tools(), answer_model=LocatorAnswer,
        verify=verify, budget=budget or Budget(max_steps=6, max_seconds=600, max_cost_usd=0.10),
        name="locator", model=model, backend=backend, **client_kw,
    )
    trace = [e.model_dump() for e in out.trace]
    if out.status != "finished" or not isinstance(out.answer, LocatorAnswer):
        return LocatorResult(steps=out.steps, cost_usd=out.cost_usd, trace=trace,
                             failure=f"{out.status}: {out.problem}")
    suggestions = []
    for cid in dict.fromkeys(out.answer.case_ids):
        row = con.execute(
            f"SELECT title, {DECISION_YEAR_SQL} FROM cases c WHERE c.cnr = ?", (cid,)
        ).fetchone()
        if row:  # the id came from a tool, so it exists; this just fetches the real title
            suggestions.append(Suggestion(case_id=cid, title=row[0], year=row[1]))
    return LocatorResult(suggestions=suggestions, reason=out.answer.reason, steps=out.steps,
                         cost_usd=out.cost_usd, trace=trace)
