import sqlite3

import pytest

from pramaan.citations.extract import Citation
from pramaan.citations.normalise import ParsedCitation
from pramaan.data.build_aliases import build_aliases
from pramaan.data.build_db import SCHEMA
from pramaan.resolve.resolver import resolve, resolve_alias


def add_case(con, cnr, title, year):
    con.execute(
        "INSERT INTO cases (cnr, title, petitioner, respondent, year, decision_date) "
        "VALUES (?, ?, 'P', 'R', ?, ?)", (cnr, title, year, f"01-01-{year}"),
    )


@pytest.fixture
def con():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    add_case(con, "C1", "Ram Lal v. State of Bihar", 1960)
    add_case(con, "C2", "A v. B", 1980)  # judgments that cite C1
    add_case(con, "C3", "C v. D", 1985)
    con.execute("INSERT INTO case_citations VALUES ('C1', 'SCR', 1960, 1, 107, 'raw')")
    para = "See Ram Lal v. State of Bihar, (1960) 2 SCC 45 : [1960] 1 SCR 107 for the rule."
    for cnr in ("C2", "C3"):
        con.execute("INSERT INTO paragraphs VALUES (?, 1, 1, ?)", (cnr, para))
    return con


def scc(page=45, volume=2, year=1960):
    return ParsedCitation(reporter="SCC", year=year, volume=volume, page=page)


def test_build_stores_one_row_per_citing_judgment(con):
    assert build_aliases(con) == 2
    rows = con.execute("SELECT DISTINCT case_id FROM citation_aliases").fetchall()
    assert rows == [("C1",)]


def test_alias_resolves_scc_number(con):
    build_aliases(con)
    r = resolve_alias(con, scc())
    assert (r.case_id, r.method) == ("C1", "alias")


def test_unknown_number_and_wrong_volume_are_none(con):
    build_aliases(con)
    assert resolve_alias(con, scc(page=999)) is None
    assert resolve_alias(con, scc(volume=3)) is None


def test_excluding_the_citing_judgment_hides_only_its_evidence(con):
    build_aliases(con)
    assert resolve_alias(con, scc(), exclude_citing="C2").case_id == "C1"  # C3 still says so
    con.execute("DELETE FROM citation_aliases WHERE citing_case = 'C3'")
    assert resolve_alias(con, scc(), exclude_citing="C2") is None


def test_conflicting_evidence_is_not_used(con):
    build_aliases(con)
    add_case(con, "C4", "Other v. Case", 1960)
    con.execute("INSERT INTO citation_aliases VALUES ('SCC', 1960, 2, 45, 'C4', 'C2')")
    assert resolve_alias(con, scc()) is None


def test_resolve_prefers_alias_over_fuzzy_and_old_db_still_works(con):
    build_aliases(con)
    cit = Citation(raw="(1960) 2 SCC 45", span=(0, 0), format="SCC", proposition="",
                   parsed=scc(), case_name="Totally Unrelated v. Name")
    assert resolve(con, cit).method == "alias"
    con.execute("DROP TABLE citation_aliases")  # a database built before this feature
    assert resolve(con, cit).case_id is None  # falls through to fuzzy, no crash


def test_citing_itself_is_ignored(con):
    con.execute("INSERT INTO paragraphs VALUES ('C1', 1, 1, "
                "'Ram Lal v. State of Bihar, (1960) 2 SCC 45 : [1960] 1 SCR 107')")
    assert build_aliases(con) == 2  # C1's own paragraph added nothing
