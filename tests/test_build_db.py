import sqlite3

import pandas as pd

from pramaan.data.build_db import build


def _row(cnr: str, year: int) -> dict:
    return {
        "cnr": cnr, "case_id": "", "title": "A versus B", "petitioner": "A", "respondent": "B",
        "decision_date": f"01-01-{year}", "year": year, "judge": "J", "citation": "",
        "nc_display": "", "path": f"{cnr}_path",
    }


def test_case_listed_under_two_years_is_stored_once(tmp_path):
    for year, cnrs in {1954: ["X1", "X2"], 1955: ["X2", "X3"]}.items():
        folder = tmp_path / "metadata" / f"year={year}"
        folder.mkdir(parents=True)
        pd.DataFrame([_row(c, year) for c in cnrs]).to_parquet(folder / "metadata.parquet")

    db = tmp_path / "t.db"
    summary = build(db_path=db, years=[1954, 1955], data_dir=tmp_path)

    rows = sqlite3.connect(db).execute("SELECT cnr, year FROM cases ORDER BY cnr").fetchall()
    assert rows == [("X1", 1954), ("X2", 1954), ("X3", 1955)]
    assert summary.n_cases == 3
