import sqlite3

from pramaan.data.build_aliases import ALIASES_SCHEMA
from pramaan.data.build_db import SCHEMA
from pramaan.data.invariants import run_invariants


def make():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.executescript(ALIASES_SCHEMA)
    con.execute(
        "INSERT INTO cases (cnr, title, pdf_path) VALUES ('C1', 'A v. B', '1990_1_1_2_EN.pdf')"
    )
    con.execute("INSERT INTO paragraphs VALUES ('C1', 1, 1, 'text')")
    return con


def by_name(con):
    return {r.name: r for r in run_invariants(con)}


def test_clean_database_passes():
    assert all(r.ok for r in run_invariants(make()))


def test_orphan_paragraph_and_self_alias_fail():
    con = make()
    con.execute("INSERT INTO paragraphs VALUES ('GHOST', 1, 1, 'x')")
    con.execute("INSERT INTO citation_aliases VALUES ('SCC', 1990, 1, 5, 'C1', 'C1')")
    r = by_name(con)
    assert not r["paragraph_without_case"].ok and not r["alias_points_at_citing_case"].ok


def test_soft_checks_report_but_do_not_fail():
    con = make()
    con.execute("INSERT INTO cases (cnr, title) VALUES ('C2', 'X v. Y')")
    r = by_name(con)
    assert r["case_without_paragraphs"].violations == 1 and r["case_without_paragraphs"].ok
