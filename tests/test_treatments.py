import sqlite3

import pytest

from pramaan.checks.treatment import adverse, treatments_of
from pramaan.citations.extract import Citation
from pramaan.citations.normalise import ParsedCitation
from pramaan.data.build_aliases import ALIASES_SCHEMA
from pramaan.data.build_db import SCHEMA
from pramaan.data.build_treatments import build_treatments, treatments_in_text
from pramaan.pipeline import check_citation

HEADNOTE = (
    "Case Law Reference Old Case v. State (1960 INSC 5) - overruled. Other Case v. Union "
    "(1961 INSC 9) - distinguished. The question is whether bail may be granted."
)


@pytest.fixture
def con():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA + ALIASES_SCHEMA)
    cases = [("OLD", "Old Case v. State", 1960), ("OTHER", "Other Case v. Union", 1961),
             ("NEW", "New Case v. Union", 1990), ("EARLY", "Early Case v. X", 1950)]
    for cnr, title, year in cases:
        pet, resp = title.split(" v. ")
        con.execute("INSERT INTO cases (cnr, title, petitioner, respondent, year, decision_date) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (cnr, title, pet, resp, year, f"01-01-{year}"))
    con.execute("INSERT INTO case_citations VALUES ('OLD', 'INSC', 1960, NULL, 5, 'r')")
    con.execute("INSERT INTO case_citations VALUES ('OTHER', 'INSC', 1961, NULL, 9, 'r')")
    con.execute("INSERT INTO paragraphs VALUES ('NEW', 1, 1, ?)", (HEADNOTE,))
    con.execute("INSERT INTO paragraphs VALUES ('OLD', 1, 1, 'Bail may be granted in a fit case.')")
    return con


def test_headnote_labels_are_read_and_resolved(con):
    rows = treatments_in_text(con, "NEW", HEADNOTE)
    assert {(r[0], r[2]) for r in rows} == {("OLD", "overruled"), ("OTHER", "distinguished")}
    assert "Old Case v. State" in rows[0][3] and "overruled" in rows[0][3]


def test_a_case_does_not_treat_itself(con):
    assert treatments_in_text(con, "OLD", HEADNOTE.replace("Other Case", "Old Case")) != []
    assert [r for r in treatments_in_text(con, "OLD", HEADNOTE) if r[0] == "OLD"] == []


def test_build_skips_a_judgment_earlier_than_the_case_it_treats(con):
    con.execute("INSERT INTO paragraphs VALUES ('EARLY', 1, 1, ?)", (HEADNOTE,))
    n = build_treatments(con)
    citing = {r[0] for r in con.execute("SELECT citing_case FROM treatments")}
    assert n == 2 and citing == {"NEW"}  # EARLY (1950) cannot treat 1960/1961 cases


def test_lookup_orders_strong_first_and_survives_missing_table(con):
    assert treatments_of(con, "OLD") == []  # no table yet
    build_treatments(con)
    found = treatments_of(con, "OLD")
    assert [t.label for t in adverse(found)] == ["overruled"] and found[0].citing_year == 1990
    assert [t.label for t in treatments_of(con, "OTHER")] == ["distinguished"]
    assert adverse(treatments_of(con, "OTHER")) == []


def _cit(page, name):
    return Citation(raw=f"1960 INSC {page}", span=(0, 10), format="NEUTRAL",
                    parsed=ParsedCitation(reporter="INSC", year=1960, volume=None, page=page),
                    case_name=name, proposition="bail may be granted", quoted_text=None,
                    para_ref=None)


def test_overruled_case_is_needs_review_not_verified(con):
    build_treatments(con)
    r = check_citation(con, _cit(5, "Old Case v. State"), use_llm=False)
    assert r.status == "NEEDS_REVIEW" and "overruled" in r.reason and r.treatments[0].strong


def test_distinguished_case_stays_verified_but_shows_treatment(con):
    build_treatments(con)
    c = _cit(9, "Other Case v. Union")
    c.parsed = ParsedCitation(reporter="INSC", year=1961, volume=None, page=9)
    r = check_citation(con, c, use_llm=False)
    assert r.status == "VERIFIED" and r.treatments[0].label == "distinguished"


def test_a_neutral_label_closes_the_group_before_it(con):
    text = ("Other Case v. Union (1961 INSC 9) - referred to. Old Case v. State (1960 INSC 5) "
            "- overruled.")
    rows = treatments_in_text(con, "NEW", text)
    assert [(r[0], r[2]) for r in rows] == [("OLD", "overruled")]  # OTHER is not accused


def test_neutral_label_without_a_dash_also_closes(con):
    text = ("Other Case v. Union (1961 INSC 9) referred to Para 2 Old Case v. State "
            "(1960 INSC 5) - overruled.")
    assert [r[0] for r in treatments_in_text(con, "NEW", text)] == ["OLD"]
