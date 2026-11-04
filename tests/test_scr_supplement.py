"""The SCR Supplement series restarts page numbers inside the same year and volume number."""

import sqlite3

import pytest

from pramaan.citations.normalise import parse_scr
from pramaan.citations.patterns import SCR
from pramaan.data.build_db import SCHEMA
from pramaan.resolve.resolver import resolve_exact


@pytest.mark.parametrize(
    "raw",
    [
        "[1992] SUPP. 2 S.C.R. 1",       # the dataset's own form
        "[1992] Supp. (2) SCR 1",
        "[1992] Supp 2 SCR 1",
        "[1992] 2 Supp. SCR 1",
        "[1996] SUPP. 10 S.C.R. 915",
    ],
)
def test_supplement_forms_get_their_own_reporter(raw):
    parsed = parse_scr(raw)
    assert parsed.reporter == "SCR-SUPP"
    assert parsed.volume is not None
    assert SCR.search(raw) is not None


def test_supplement_volume_and_page():
    p = parse_scr("[1996] SUPP. 10 S.C.R. 915")
    assert (p.year, p.volume, p.page) == (1996, 10, 915)
    assert parse_scr("[1992] Supp. (2) SCR 1").volume == 2


def test_regular_series_is_unchanged():
    p = parse_scr("[1992] 2 S.C.R. 1")
    assert (p.reporter, p.year, p.volume, p.page) == ("SCR", 1992, 2, 1)
    assert parse_scr("[1950] SCR 88").volume is None


def test_supplement_citation_is_found_in_extracted_text():
    text = "See Joshi v. Pande, [1992] Supp. (2) SCR 1 at 5."
    assert SCR.search(text).group(0).strip().endswith("SCR 1")


@pytest.fixture
def con():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    for cnr in ("REG", "SUP"):
        con.execute(
            "INSERT INTO cases (cnr, title, year, decision_date) VALUES (?, ?, 1992, '01-01-1992')",
            (cnr, cnr),
        )
    con.execute("INSERT INTO case_citations VALUES ('REG', 'SCR', 1992, 2, 1, 'raw')")
    con.execute("INSERT INTO case_citations VALUES ('SUP', 'SCR-SUPP', 1992, 2, 1, 'raw')")
    return con


def test_supplement_citation_never_resolves_to_the_regular_case(con):
    assert resolve_exact(con, parse_scr("[1992] Supp. (2) SCR 1")).case_id == "SUP"
    assert resolve_exact(con, parse_scr("[1992] 2 SCR 1")).case_id == "REG"


def test_supplement_without_volume_does_not_fall_into_the_regular_series(con):
    assert resolve_exact(con, parse_scr("[1992] Supp. SCR 1")).case_id == "SUP"
