import sqlite3

import pytest

from pramaan.citations.normalise import ParsedCitation
from pramaan.data.build_db import SCHEMA
from pramaan.resolve.resolver import resolve_exact


@pytest.fixture
def con():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    cases = [
        ("C1", "A versus B", 1960), ("C2", "X versus Y", 2014), ("C3", "P versus Q", 2014),
    ]
    for cnr, title, year in cases:
        con.execute(
            "INSERT INTO cases (cnr, title, year) VALUES (?, ?, ?)", (cnr, title, year)
        )
    citations = [
        ("C1", "SCR", 1960, 1, 107), ("C1", "INSC", 1960, None, 5),
        ("C2", "INSC", 2014, None, 222), ("C3", "INSC", 2014, None, 222),  # shared number
    ]
    for cnr, reporter, year, volume, page in citations:
        con.execute(
            "INSERT INTO case_citations VALUES (?, ?, ?, ?, ?, 'raw')",
            (cnr, reporter, year, volume, page),
        )
    return con


def _p(reporter, year, page, volume=None):
    return ParsedCitation(reporter=reporter, year=year, volume=volume, page=page)


def test_exact_neutral(con):
    r = resolve_exact(con, _p("INSC", 1960, 5))
    assert (r.case_id, r.method, r.confidence) == ("C1", "neutral", 1.0)


def test_exact_scr_with_volume(con):
    r = resolve_exact(con, _p("SCR", 1960, 107, volume=1))
    assert (r.case_id, r.method) == ("C1", "reporter")


def test_scr_with_wrong_volume_is_not_found(con):
    assert resolve_exact(con, _p("SCR", 1960, 107, volume=2)) is None


def test_scr_without_volume_still_matches(con):
    assert resolve_exact(con, _p("SCR", 1960, 107)).case_id == "C1"


def test_shared_number_is_ambiguous_not_guessed(con):
    r = resolve_exact(con, _p("INSC", 2014, 222))
    assert r.case_id is None and r.method == "ambiguous"
    assert {a.case_id for a in r.alternatives} == {"C2", "C3"}


def test_unknown_number_returns_none(con):
    assert resolve_exact(con, _p("INSC", 2014, 9999)) is None


def test_scc_and_air_have_no_exact_lookup(con):
    assert resolve_exact(con, _p("SCC", 2009, 24, volume=5)) is None
    assert resolve_exact(con, _p("AIR", 1962, 253)) is None
