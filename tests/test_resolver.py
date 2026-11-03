import sqlite3

import pytest

from pramaan.citations.extract import Citation
from pramaan.citations.normalise import ParsedCitation
from pramaan.data.build_db import SCHEMA
from pramaan.resolve.names import find_name_candidates, split_parties
from pramaan.resolve.resolver import resolve, resolve_exact, resolve_fuzzy


@pytest.fixture
def con():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    cases = [
        ("C1", "A versus B", 1960), ("C2", "X versus Y", 2014), ("C3", "P versus Q", 2014),
    ]
    for cnr, title, year in cases:
        con.execute(
            "INSERT INTO cases (cnr, title, year, decision_date) VALUES (?, ?, ?, ?)",
            (cnr, title, year, f"01-01-{year}"),
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


# ---- fuzzy party-name resolution ----

@pytest.fixture
def names_con():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    rows = [
        ("N1", "OM KUMAR AND ORS.", "UNION OF INDIA", 2000),
        ("N2", "ARUN KUMAR", "UNION OF INDIA", 2000),
        ("N3", "OM KUMAR AND ORS.", "UNION OF INDIA", 1980),  # same names, too early for 2001
        ("N4", "RAMESH CHANDRA", "STATE OF BIHAR", 1995),
        ("N5", "RAMESH CHANDRA", "STATE OF BIHAR", 1995),  # a true twin of N4
    ]
    for cnr, pet, resp, year in rows:
        con.execute(
            "INSERT INTO cases (cnr, title, petitioner, respondent, year, decision_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cnr, f"{pet} versus {resp}", pet, resp, year, f"01-01-{year}"),
        )
    con.execute(
        "INSERT INTO names_fts(rowid, petitioner, respondent) "
        "SELECT rowid, petitioner, respondent FROM cases"
    )
    return con


def test_split_parties_handles_the_usual_spellings():
    assert split_parties("A v. B") == ("A", "B")
    assert split_parties("A vs. B") == ("A", "B")
    assert split_parties("A -vs- B") == ("A", "B")
    assert split_parties("A versus B") == ("A", "B")
    assert split_parties("Just a name") is None


def test_candidates_respect_the_year_window(names_con):
    found = find_name_candidates(names_con, "Om Kumar v. Union of India", year=2001)
    assert [c.case_id for c in found][0] == "N1"
    assert "N3" not in {c.case_id for c in found}  # decided 1980, outside 1999-2001


def test_party_suffixes_do_not_hurt_the_score(names_con):
    best = find_name_candidates(names_con, "M/s Om Kumar & Ors. v. Union of India", 2001)[0]
    assert best.case_id == "N1" and best.score == 1.0


def test_fuzzy_resolves_a_clear_winner(names_con):
    r = resolve_fuzzy(names_con, "Om Kumar v. Union of India", 2001, threshold=0.85)
    assert (r.case_id, r.method) == ("N1", "fuzzy")


def test_fuzzy_below_threshold_is_none_not_a_guess(names_con):
    r = resolve_fuzzy(names_con, "Arun Kumar v. Union of India", 2001, threshold=1.01)
    assert r.case_id is None and r.method == "none"
    assert r.alternatives  # but the closest cases are still shown


def test_fuzzy_twins_are_ambiguous(names_con):
    r = resolve_fuzzy(names_con, "Ramesh Chandra v. State of Bihar", 1995, threshold=0.85)
    assert r.case_id is None and r.method == "ambiguous"
    assert {a.case_id for a in r.alternatives} == {"N4", "N5"}


def test_no_case_name_means_none(names_con):
    assert resolve_fuzzy(names_con, None, 2001, threshold=0.85).method == "none"


def test_resolve_prefers_exact_number_over_name(con):
    cit = Citation(
        raw="1960 INSC 5", span=(0, 11), format="NEUTRAL", proposition="",
        parsed=_p("INSC", 1960, 5), case_name="Something Else v. Wrong Name",
    )
    r = resolve(con, cit)
    assert (r.case_id, r.method) == ("C1", "neutral")


def test_and_others_is_stripped_like_and_ors():
    from pramaan.citations.normalise import normalise_party_name

    assert normalise_party_name("VIDYA DROLIA AND OTHERS") == "VIDYA DROLIA"
    assert normalise_party_name("VIDYA DROLIA & ANOTHER") == "VIDYA DROLIA"


def test_name_with_only_a_company_suffix_cannot_match(names_con):
    # The extractor sometimes truncates "X Pvt. Ltd. v. Y" to "Ltd. v. Y".
    assert find_name_candidates(names_con, "Ltd. v. Union of India", 2001) == []
    assert find_name_candidates(names_con, "Private Limited v. Union of India", 2001) == []


def test_year_window_uses_the_decision_date_not_the_volume_year(names_con):
    # A 1955-volume case decided in Dec 1954 must be found by a citation that says 1954.
    names_con.execute(
        "INSERT INTO cases (cnr, title, petitioner, respondent, year, decision_date) "
        "VALUES ('N9', 'KIRAN SINGH versus CHAMAN PASWAN', 'KIRAN SINGH', 'CHAMAN PASWAN', "
        "1955, '20-12-1954')"
    )
    names_con.execute(
        "INSERT INTO names_fts(rowid, petitioner, respondent) "
        "SELECT rowid, petitioner, respondent FROM cases WHERE cnr = 'N9'"
    )
    found = find_name_candidates(names_con, "Kiran Singh v. Chaman Paswan", year=1954)
    assert found and found[0].case_id == "N9" and found[0].year == 1954


def test_near_tie_prefers_the_case_decided_nearest_the_cited_year(names_con):
    # N4/N5 are twins decided 1995; add a 1994 twin. A citation dated 1995 should pick a 1995 case
    # only if exactly one is closest, so with two 1995 twins it stays ambiguous.
    r = resolve_fuzzy(names_con, "Ramesh Chandra v. State of Bihar", 1995, threshold=0.85)
    assert r.method == "ambiguous"
    names_con.execute("DELETE FROM cases WHERE cnr = 'N5'")
    names_con.execute("INSERT INTO names_fts(names_fts) VALUES('rebuild')")
    r = resolve_fuzzy(names_con, "Ramesh Chandra v. State of Bihar", 1995, threshold=0.85)
    assert (r.case_id, r.method) == ("N4", "fuzzy")


def test_word_choice_is_deterministic():
    from pramaan.resolve.names import fts_query

    # Four 5-letter words tie on length. The two kept must be the first two alphabetically.
    assert fts_query("Zebra Yacht Xerox Wagon", "Union") == '"WAGON" OR "XEROX" OR "UNION"'
