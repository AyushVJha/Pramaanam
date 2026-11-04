import json
import sqlite3

import pytest

from pramaan.citations.extract import Citation
from pramaan.citations.normalise import ParsedCitation
from pramaan.data.build_db import SCHEMA
from pramaan.llm.client import RawReply
from pramaan.pipeline import check_citation
from pramaan.report import render_report

PARA2 = "Anticipatory bail may be granted where the court finds no prima facie case against him."


@pytest.fixture
def con():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO cases (cnr, title, petitioner, respondent, year, decision_date) "
        "VALUES ('C1', 'Ram Lal v. State of Bihar', 'Ram Lal', 'State of Bihar', "
        "1960, '01-01-1960')"
    )
    con.execute("INSERT INTO case_citations VALUES ('C1', 'INSC', 1960, NULL, 5, 'raw')")
    for n, text in [(1, "The appellant was a clerk."), (2, PARA2)]:
        con.execute("INSERT INTO paragraphs VALUES ('C1', ?, 1, ?)", (n, text))
    return con


class Fake:
    def __init__(self, verdict="supported", quote="Anticipatory bail may be granted"):
        self.calls = 0
        self.text = json.dumps({
            "verdict": verdict, "reason": "r",
            "evidence": [{"para_no": 2, "quote": quote}] if quote else [],
        })

    def create(self, **kw):
        self.calls += 1
        return RawReply(text=self.text, input_tokens=100, output_tokens=20)


def cit(raw="1960 INSC 5", name="Ram Lal v. State of Bihar", quote=None, para=None,
        parsed=True, prop="Anticipatory bail may be granted without a prima facie case."):
    return Citation(
        raw=raw, span=(0, len(raw)), format="INSC",
        parsed=ParsedCitation(reporter="INSC", year=1960, volume=None, page=5) if parsed else None,
        case_name=name, proposition=prop, quoted_text=quote, para_ref=para,
    )


def run(con, citation, fake=None, *, tmp, **kw):
    return check_citation(
        con, citation, backend=fake or Fake(),
        cache_dir=tmp / "c", usage_log=tmp / "u.jsonl", **kw,
    )


def test_all_good_is_verified(con, tmp_path):
    r = run(con, cit(), tmp=tmp_path, model="claude-haiku-5-5")
    assert r.status == "VERIFIED" and r.cost_usd > 0


def test_unresolved_is_not_found_never_fake(con, tmp_path):
    r = run(con, cit(raw="2099 INSC 1", name=None, parsed=False), tmp=tmp_path)
    assert r.status == "NOT_FOUND_IN_CORPUS"
    assert "does not mean the case is fake" in r.reason


def test_wrong_name_is_name_mismatch_and_skips_llm(con, tmp_path):
    fake = Fake()
    r = run(con, cit(name="Totally Different v. Other Person"), fake, tmp=tmp_path)
    assert r.status == "NAME_MISMATCH" and fake.calls == 0


def test_invented_quote_is_misquote_and_skips_llm(con, tmp_path):
    fake = Fake()
    r = run(con, cit(quote="Bail is a fundamental and absolute right of every accused"), fake,
            tmp=tmp_path)
    assert r.status == "MISQUOTE" and fake.calls == 0


def test_quote_in_other_paragraph_is_wrong_paragraph(con, tmp_path):
    r = run(con, cit(quote="Anticipatory bail may be granted where the court finds", para=9),
            tmp=tmp_path)
    assert r.status == "WRONG_PARAGRAPH"


def test_judge_verdicts_map_to_statuses(con, tmp_path):
    for verdict, status in [("not_supported", "UNSUPPORTED"), ("contradicted", "CONTRADICTED"),
                            ("partially_supported", "NEEDS_REVIEW")]:
        r = run(con, cit(), Fake(verdict), tmp=tmp_path / verdict)
        assert r.status == status


def test_no_llm_flag_never_verifies(con, tmp_path):
    fake = Fake()
    r = run(con, cit(), fake, tmp=tmp_path, use_llm=False)
    assert r.status == "NEEDS_REVIEW" and fake.calls == 0


def test_report_lists_status_evidence_and_disclaimer(con, tmp_path):
    out = render_report([run(con, cit(), tmp=tmp_path)])
    assert "[VERIFIED]" in out and "para 2" in out and "A lawyer decides" in out
    assert render_report([]) == "No citations found in the draft."


def test_annexure_formats_carry_disclaimer_escape_html_and_state_checks_run(con, tmp_path):
    from pramaan.report import DISCLAIMER, render_html, render_markdown

    hostile = cit(raw="1960 INSC 5<script>x()</script>")
    ok = run(con, hostile, tmp=tmp_path, model="claude-haiku-5-5")
    meta = {"source": "draft<x>.txt", "date": "2026-11-04", "llm_used": True, "model": "m"}
    md = render_markdown([ok], **meta)
    assert DISCLAIMER in md and "| 1 |" in md and "support (model: m)" in md
    page = render_html([ok], **meta)
    assert "<script>" not in page and "&lt;script&gt;" in page and "draft&lt;x&gt;.txt" in page
    off = render_markdown([ok], source="d", date="d", llm_used=False, model=None)
    assert "Support check: not run" in off
