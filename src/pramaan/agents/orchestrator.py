"""Run the deterministic checks first, then let agents add what they can. (A5)

Order for each citation:
1. the deterministic pipeline (no AI). This alone decides VERIFIED and all hard findings;
2. if the case was found and there is a proposition to test, the reading agent checks support;
   if the citation did not resolve, the locator agent suggests candidates;
3. the guard (agents/guard.py) compares the final status with the deterministic one. A change an
   agent is not allowed to make is thrown away and the deterministic report is kept;
4. a draft-level budget (calls, dollars, seconds) stops agents when used up; the rest of the
   citations still get their deterministic result, with a note saying why no agent ran.

Any agent failure (timeout, bad output, exception) leaves the deterministic report in place.
"""

import logging
import sqlite3
import time

from pydantic import BaseModel

from pramaan.agents.guard import allowed_change
from pramaan.agents.locator import locate
from pramaan.agents.runtime import Budget
from pramaan.agents.support_agent import agent_support
from pramaan.checks.support import SupportResult
from pramaan.citations.extract import Citation, extract
from pramaan.pipeline import CitationReport, check_citation

log = logging.getLogger(__name__)


class DraftBudget(BaseModel):
    """Limits for all agent work on one draft."""

    max_agent_calls: int = 20  # citations that may get an agent run
    max_cost_usd: float = 1.00
    max_seconds: float = 3600.0
    per_run: Budget = Budget(max_steps=7, max_seconds=600, max_cost_usd=0.10)


class Spend:
    def __init__(self, budget: DraftBudget):
        self.budget = budget
        self.calls, self.cost, self.started = 0, 0.0, time.perf_counter()

    def exhausted(self) -> str | None:
        b = self.budget
        if self.calls >= b.max_agent_calls:
            return f"agent limit of {b.max_agent_calls} citations per draft reached"
        if self.cost >= b.max_cost_usd:
            return f"agent cost limit of ${b.max_cost_usd:.2f} per draft reached"
        if time.perf_counter() - self.started >= b.max_seconds:
            return "agent time limit per draft reached"
        return None


def _with_note(report: CitationReport, note: str) -> CitationReport:
    return report.model_copy(update={"agent_note": note})


def review_citation(
    con: sqlite3.Connection,
    citation: Citation,
    spend: Spend,
    *,
    model: str | None = None,
    backend=None,
    **client_kw,
) -> CitationReport:
    base = check_citation(con, citation, use_llm=False)
    wants_support = (
        base.case_id is not None and base.status in ("VERIFIED", "NEEDS_REVIEW")
        and bool(citation.proposition.strip())
    )
    wants_locator = base.status == "NOT_FOUND_IN_CORPUS"
    if not (wants_support or wants_locator):
        return base
    stop = spend.exhausted()
    if stop:
        return _with_note(base, f"Agents skipped: {stop}.")
    spend.calls += 1
    try:
        if wants_support:
            return _support_step(con, citation, base, spend, model, backend, client_kw)
        return _locator_step(con, citation, base, spend, model, backend, client_kw)
    except Exception as e:  # an agent must never break the report
        log.exception("agent step failed")
        note = f"Agent step failed ({type(e).__name__}); deterministic result kept."
        return _with_note(base, note)


def _support_step(con, citation, base, spend, model, backend, client_kw) -> CitationReport:
    result: SupportResult = agent_support(
        con, base.case_id, citation.proposition, budget=spend.budget.per_run, model=model,
        backend=backend, **client_kw,
    )
    spend.cost += result.cost_usd
    final = check_citation(
        con, citation, use_llm=True, support_fn=lambda *a, **k: result
    )
    update: dict = {"agent_trace": result.trace, "cost_usd": result.cost_usd}
    if result.failure:
        update["agent_note"] = (
            f"The reading agent did not finish ({result.failure[:120]}); the deterministic "
            "result stands."
        )
    final = final.model_copy(update=update)
    if not allowed_change(base.status, final.status):
        return _with_note(base, "Agent result rejected by the status guard; deterministic kept.")
    return final


def _locator_step(con, citation, base, spend, model, backend, client_kw) -> CitationReport:
    found = locate(
        con, raw=citation.raw, case_name=citation.case_name, context=citation.proposition,
        budget=spend.budget.per_run, model=model, backend=backend, **client_kw,
    )
    spend.cost += found.cost_usd
    update: dict = {"agent_trace": found.trace, "cost_usd": found.cost_usd}
    if found.suggestions:
        names = "; ".join(f"{s.title} ({s.year})" for s in found.suggestions)
        update["suggestions"] = found.suggestions
        update["status"] = "NEEDS_REVIEW"
        update["reason"] = (
            f"{base.reason} Possible matches found by search (not confirmed): {names}. "
            "Check that one of these is the case meant."
        )
    final = base.model_copy(update=update)
    if not allowed_change(base.status, final.status):
        return _with_note(base, "Agent result rejected by the status guard; deterministic kept.")
    return final


def review_text(
    con: sqlite3.Connection, text: str, budget: DraftBudget | None = None, **kw
) -> list[CitationReport]:
    spend = Spend(budget or DraftBudget())
    return [review_citation(con, c, spend, **kw) for c in extract(text)]
