"""Tests for the tools, the reading agent, the locator and the orchestrator (fake model only)."""

import itertools
import json
import sqlite3

import pytest

from pramaan.agents.locator import locate
from pramaan.agents.orchestrator import DraftBudget, Spend, review_citation
from pramaan.agents.support_agent import agent_support
from pramaan.agents.tools import (
    CaseFinder,
    CitationArgs,
    JudgmentReader,
    PartyArgs,
    ReadArgs,
    SearchArgs,
    TextArgs,
)
from pramaan.citations.extract import Citation
from pramaan.citations.normalise import ParsedCitation
from pramaan.data.build_aliases import ALIASES_SCHEMA
from pramaan.data.build_db import SCHEMA
from pramaan.llm.client import RawReply

PARA2 = "Anticipatory bail may be granted where the court finds no prima facie case against him."
_n = itertools.count()


@pytest.fixture
def con():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.executescript(ALIASES_SCHEMA)
    for cnr, title, pet, resp, year in [
        ("C1", "Ramnarayan Lalwani v. State of Bihar", "Ramnarayan Lalwani", "State of Bihar",
         1960),
        ("C2", "Mohan Singh v. Union of India", "Mohan Singh", "Union of India", 1985),
    ]:
        con.execute(
            "INSERT INTO cases (cnr, title, petitioner, respondent, year, decision_date) "
            "VALUES (?, ?, ?, ?, ?, ?)", (cnr, title, pet, resp, year, f"01-01-{year}"),
        )
    con.execute("INSERT INTO case_citations VALUES ('C1', 'INSC', 1960, NULL, 5, 'raw')")
    for n, text in [(1, "The appellant was a clerk."), (2, PARA2),
                    (3, "The statute of limitation bars a suit filed after three years.")]:
        con.execute("INSERT INTO paragraphs VALUES ('C1', ?, 1, ?)", (n, text))
    con.execute("INSERT INTO paragraphs VALUES ('C2', 1, 1, 'Preventive detention requires care.')")
    con.execute("INSERT INTO paragraphs_fts(rowid, text) SELECT rowid, text FROM paragraphs")
    con.execute("INSERT INTO names_fts(rowid, petitioner, respondent) "
                "SELECT rowid, petitioner, respondent FROM cases")
    return con


class Scripted:
    def __init__(self, *turns):
        self.turns, self.calls = [json.dumps(t) for t in turns], 0

    def create(self, **kw):
        text = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        return RawReply(text=text, input_tokens=100, output_tokens=20)


def tool(name, **args):
    return {"action": "tool", "tool": name, "args": args}


def finish(**answer):
    return {"action": "finish", "answer": answer}


def kw(tmp_path):
    return {"cache_dir": tmp_path / f"c{next(_n)}", "usage_log": tmp_path / "u.jsonl",
            "model": "claude-haiku-5-5"}


def cit(raw="1960 INSC 5", name="Ramnarayan Lalwani v. State of Bihar",
        prop="Anticipatory bail may be granted.", parsed=True):
    return Citation(
        raw=raw, span=(0, len(raw)), format="INSC",
        parsed=ParsedCitation(reporter="INSC", year=1960, volume=None, page=5) if parsed else None,
        case_name=name, proposition=prop, quoted_text=None, para_ref=None,
    )


# --- tools ---
def test_reader_search_read_and_remember(con):
    r = JudgmentReader(con, "C1")
    out = r.search(SearchArgs(query="anticipatory bail"))
    assert "[para 2]" in out and r.shown == {2} and r.read == set()
    assert "Anticipatory bail may be granted" in r.read_paragraph(ReadArgs(para_no=2))
    assert r.read == {2}
    assert "no paragraph 99" in r.read_paragraph(ReadArgs(para_no=99))
    assert "No paragraph shares" in r.search(SearchArgs(query="zzz qqq"))


def test_finder_tools(con):
    f = CaseFinder(con)
    both = PartyArgs(petitioner="Ramnarayan Lalwani", respondent="State of Bihar")
    assert "C1" in f.by_party(both)
    assert "C1" in f.by_citation(CitationArgs(reporter="insc", year=1960, page=5))
    assert "No judgment" in f.by_citation(CitationArgs(reporter="SCR", year=1900, page=1))
    assert "C2" in f.by_text(TextArgs(query="preventive detention"))
    assert "four letters" in f.by_text(TextArgs(query="a b"))
    assert {"C1", "C2"} <= f.seen


def test_text_search_survives_quotes_and_operators(con):
    out = CaseFinder(con).by_text(TextArgs(query='detention" OR NEAR( ) *'))
    assert "C2" in out  # punctuation is stripped before it reaches FTS


def test_tools_cannot_write(con):
    r = JudgmentReader(con, "C1")
    before = con.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0]
    r.search(SearchArgs(query="'; DROP TABLE paragraphs; --"))
    assert con.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0] == before


# --- support agent ---
def test_agent_reads_then_supports_with_looked_up_quote(con, tmp_path):
    fake = Scripted(tool("read_paragraph", para_no=2),
                    finish(verdict="supported", paras=[2], reason="para 2 says so"))
    r = agent_support(con, "C1", "anticipatory bail may be granted", backend=fake, **kw(tmp_path))
    assert r.verdict == "supported" and r.steps == 2
    assert r.evidence[0].para_no == 2 and r.evidence[0].quote in PARA2
    assert [e["kind"] for e in r.trace] == ["model", "tool", "model", "final"]


def test_agent_cannot_rely_on_unread_paragraph(con, tmp_path):
    fake = Scripted(finish(verdict="supported", paras=[2], reason="x"),
                    tool("read_paragraph", para_no=2),
                    finish(verdict="supported", paras=[2], reason="x"))
    r = agent_support(con, "C1", "anticipatory bail may be granted", backend=fake, **kw(tmp_path))
    assert r.verdict == "supported" and r.steps == 3  # first finish rejected, then it read


def test_agent_unread_twice_falls_back_to_cannot_determine(con, tmp_path):
    fake = Scripted(finish(verdict="supported", paras=[2], reason="x"))
    r = agent_support(con, "C1", "anticipatory bail may be granted", backend=fake, **kw(tmp_path))
    assert r.verdict == "cannot_determine" and "not read in full" in r.failure


def test_agent_not_supported_needs_a_search(con, tmp_path):
    fake = Scripted(finish(verdict="not_supported", paras=[], reason="x"),
                    tool("search_judgment", query="limitation suit"),
                    finish(verdict="not_supported", paras=[], reason="x"))
    r = agent_support(con, "C1", "anticipatory bail may be granted", backend=fake, **kw(tmp_path))
    assert r.verdict == "not_supported" and r.steps == 3


def test_agent_no_text_is_cannot_determine_without_a_call(con, tmp_path):
    fake = Scripted(finish(verdict="supported", paras=[], reason="x"))
    r = agent_support(con, "NOPE", "bail", backend=fake, **kw(tmp_path))
    assert r.verdict == "cannot_determine" and fake.calls == 0


# --- locator ---
def test_locator_suggests_only_ids_it_was_shown(con, tmp_path):
    party = tool("find_by_party_names", petitioner="Ramnarayan Lalwani",
                 respondent="State of Bihar")
    fake = Scripted(party, finish(case_ids=["C1"], reason="names match"))
    r = locate(con, raw="(1960) 2 SCC 77", case_name="Ramnarayan Lalwani v. State of Bihar",
               context="bail", backend=fake, **kw(tmp_path))
    assert [s.case_id for s in r.suggestions] == ["C1"]
    assert r.suggestions[0].title.startswith("Ramnarayan")


def test_locator_cannot_invent_an_id(con, tmp_path):
    fake = Scripted(finish(case_ids=["C1"], reason="guess"))
    r = locate(con, raw="x", case_name=None, context="c", backend=fake, **kw(tmp_path))
    assert r.suggestions == [] and "never shown" in r.failure


def test_locator_may_find_nothing(con, tmp_path):
    fake = Scripted(tool("find_by_text", query="unknown topic words"),
                    finish(case_ids=[], reason="nothing fits"))
    r = locate(con, raw="x", case_name=None, context="c", backend=fake, **kw(tmp_path))
    assert r.suggestions == [] and r.failure is None


# --- orchestrator ---
def test_orchestrator_agent_can_lower_but_run_is_traced(con, tmp_path):
    fake = Scripted(tool("search_judgment", query="limitation"),
                    finish(verdict="not_supported", paras=[], reason="not there"))
    r = review_citation(con, cit(), Spend(DraftBudget()), backend=fake, **kw(tmp_path))
    assert r.status == "UNSUPPORTED" and r.agent_trace


def test_orchestrator_never_creates_verified_from_not_found(con, tmp_path):
    party = tool("find_by_party_names", petitioner="Ramnarayan Lalwani",
                 respondent="State of Bihar")
    fake = Scripted(party, finish(case_ids=["C1"], reason="match"))
    c = cit(raw="2099 INSC 1", name=None, parsed=False)
    r = review_citation(con, c, Spend(DraftBudget()), backend=fake, **kw(tmp_path))
    assert r.status == "NEEDS_REVIEW" and r.suggestions[0].case_id == "C1"
    assert "not confirmed" in r.reason


def test_orchestrator_budget_stops_agents_but_keeps_result(con, tmp_path):
    fake = Scripted(finish(verdict="supported", paras=[], reason="x"))
    spend = Spend(DraftBudget(max_agent_calls=0))
    r = review_citation(con, cit(), spend, backend=fake, **kw(tmp_path))
    assert r.status == "VERIFIED" and fake.calls == 0 and "Agents skipped" in r.agent_note


def test_orchestrator_agent_exception_keeps_deterministic(con, tmp_path):
    class Boom:
        def create(self, **kw):
            raise RuntimeError("server down")

    r = review_citation(con, cit(), Spend(DraftBudget()), backend=Boom(), **kw(tmp_path))
    assert r.status == "VERIFIED" and "did not finish" in r.agent_note


def test_orchestrator_agent_giving_up_keeps_verified(con, tmp_path):
    fake = Scripted("garbage")  # a non-JSON reply, repeated
    fake.turns = ["not json at all"]
    r = review_citation(con, cit(), Spend(DraftBudget()), backend=fake, **kw(tmp_path))
    assert r.status == "VERIFIED"  # cannot_determine never removes the deterministic tick


def test_orchestrator_skips_agents_when_name_mismatch(con, tmp_path):
    fake = Scripted(finish(verdict="supported", paras=[], reason="x"))
    r = review_citation(con, cit(name="Totally Different v. Other Person"), Spend(DraftBudget()),
                        backend=fake, **kw(tmp_path))
    assert r.status == "NAME_MISMATCH" and fake.calls == 0


def test_report_shows_what_the_agents_did(con, tmp_path):
    from pramaan.report import render_html, render_markdown

    fake = Scripted(tool("search_judgment", query="limitation"),
                    finish(verdict="not_supported", paras=[], reason="not there"))
    r = review_citation(con, cit(), Spend(DraftBudget()), backend=fake, **kw(tmp_path))
    meta = {"source": "d.txt", "date": "2026-11-05", "llm_used": True, "model": "m"}
    assert "How the agents checked" in render_markdown([r], **meta)
    assert "looked up: search_judgment" in render_html([r], **meta)
