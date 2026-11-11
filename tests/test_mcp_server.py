import asyncio
import sqlite3

import pytest

pytest.importorskip("mcp")

from pramaan.data.build_db import SCHEMA  # noqa: E402
from pramaan.mcp_server import MAX_CHARS, mcp, run_check  # noqa: E402

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
    con.execute("INSERT INTO paragraphs VALUES ('C1', 2, 1, ?)", (PARA2,))
    return con


def test_a_real_citation_with_a_true_quote_is_verified(con):
    out = run_check(con, f'Ram Lal v. State of Bihar, 1960 INSC 5: "{PARA2[:50]}"')
    assert out["citations_found"] == 1
    r = out["results"][0]
    assert r["status"] == "VERIFIED" and r["proven_by_citation_number"] is True


def test_an_altered_quote_is_a_misquote_not_verified(con):
    text = 'Ram Lal v. State of Bihar, 1960 INSC 5: "Anticipatory bail may never be granted"'
    out = run_check(con, text)
    assert out["results"][0]["status"] != "VERIFIED"


def test_unknown_citation_is_not_called_fake(con):
    out = run_check(con, "Foo v. Bar, 1999 INSC 777 was decided earlier.")
    statuses = {r["status"] for r in out["results"]}
    assert statuses <= {"NOT_FOUND_IN_CORPUS", "CANNOT_VERIFY"}


def test_oversized_text_is_refused(con):
    assert "error" in run_check(con, "x" * (MAX_CHARS + 1))


def test_the_two_tools_are_registered():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in getattr(tools, "tools", tools)}
    assert names == {"verify_citations", "verify_quote"}
