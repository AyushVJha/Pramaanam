"""The reading agent for the support check. (A3)

Same question as checks/support.py: does this judgment support this proposition? But instead of
one look at five paragraphs, the agent may search the judgment again with its own words and read
paragraphs in full, inside a budget. It returns the same SupportResult, so the pipeline treats the
two interchangeably. Its answer is checked by code:
- evidence is by pointer: it names paragraph numbers, the quote we show is looked up by us;
- a paragraph can only be relied on if the agent READ it in full (not just saw a snippet);
- "not supported" needs at least one search behind it (no lazy refusal).
"""

import sqlite3

from pydantic import BaseModel

from pramaan.agents.runtime import AgentOutcome, Budget, run_agent
from pramaan.agents.tools import JudgmentReader
from pramaan.checks.support import (
    TOP_K,
    Evidence,
    PointerAnswer,
    SupportResult,
    best_sentence,
    rank_paragraphs,
)
from pramaan.llm.client import Backend
from pramaan.llm.prompts import SUPPORT_AGENT_SYSTEM

NEEDS_PARAS = ("supported", "partially_supported", "contradicted")


def _task(proposition: str, first_hits: list[tuple[int, str]]) -> str:
    snippets = "\n".join(
        f"[para {n}] {best_sentence(t, proposition, 300)}" for n, t in first_hits
    ) or "(the keyword search found nothing)"
    return f"PROPOSITION:\n{proposition}\n\nFIRST SNIPPETS (keyword search):\n{snippets}"


def make_verifier(reader: JudgmentReader):
    def verify(answer: BaseModel) -> str | None:
        assert isinstance(answer, PointerAnswer)
        if answer.verdict in NEEDS_PARAS:
            if not answer.paras:
                return f"verdict {answer.verdict} needs paragraph numbers in paras"
            for n in answer.paras:
                if n not in reader.read:
                    return f"paragraph {n} was not read in full; call read_paragraph({n}) first"
        if answer.verdict == "not_supported" and reader.searches == 0:
            return "not_supported needs at least one search_judgment call"
        return None

    return verify


def _result(out: AgentOutcome, reader: JudgmentReader, proposition: str,
            given: list[int]) -> SupportResult:
    trace = [e.model_dump() for e in out.trace]
    if out.status == "finished" and isinstance(out.answer, PointerAnswer):
        a = out.answer
        evidence = [
            Evidence(para_no=n, quote=best_sentence(reader.text[n], proposition))
            for n in dict.fromkeys(a.paras)
        ]
        return SupportResult(
            verdict=a.verdict, evidence=evidence, reason=a.reason, attempts=out.steps,
            paragraphs_given=sorted(reader.shown), cost_usd=out.cost_usd, steps=out.steps,
            latency_s=sum(e.seconds for e in out.trace if e.kind == "model"), trace=trace,
        )
    return SupportResult(
        verdict="cannot_determine", reason="The reading agent did not reach a verified answer.",
        attempts=out.steps, paragraphs_given=given, cost_usd=out.cost_usd, steps=out.steps,
        failure=f"{out.status}: {out.problem}", trace=trace,
    )


def agent_support(
    con: sqlite3.Connection,
    case_id: str,
    proposition: str,
    *,
    k: int = TOP_K,
    budget: Budget | None = None,
    model: str | None = None,
    backend: Backend | None = None,
    **client_kw,
) -> SupportResult:
    """Drop-in replacement for check_support that uses the reading agent."""
    reader = JudgmentReader(con, case_id)
    first = rank_paragraphs(reader.paragraphs, proposition, k)
    if not reader.paragraphs:
        return SupportResult(verdict="cannot_determine", reason="No text for this judgment.",
                             attempts=0)
    reader.shown.update(n for n, _ in first)
    out = run_agent(
        _task(proposition, first), system=SUPPORT_AGENT_SYSTEM, tools=reader.tools(),
        answer_model=PointerAnswer, verify=make_verifier(reader),
        budget=budget or Budget(max_steps=7, max_seconds=600, max_cost_usd=0.10),
        name="support", model=model, backend=backend, **client_kw,
    )
    return _result(out, reader, proposition, [n for n, _ in first])

