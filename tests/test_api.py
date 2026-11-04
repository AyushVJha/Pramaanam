import io
import sqlite3

import pytest
from docx import Document
from fastapi.testclient import TestClient

from pramaan.api.app import MAX_UPLOAD_BYTES, create_app
from pramaan.data.build_db import SCHEMA


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO cases (cnr, title, petitioner, respondent, year, decision_date) "
        "VALUES ('C1', 'Ram Lal v. State of Bihar', 'Ram Lal', 'State of Bihar', "
        "1960, '01-01-1960')"
    )
    con.execute("INSERT INTO case_citations VALUES ('C1', 'INSC', 1960, NULL, 5, 'raw')")
    con.commit()
    con.close()
    return path


def upload(client, name, content, path="/check", **data):
    return client.post(path, files={"draft": (name, content)}, data=data)


def test_health_and_home_page(db_path):
    c = TestClient(create_app(db_path))
    assert c.get("/health").json() == {"status": "ok", "database": True}
    page = c.get("/").text
    assert "CC-BY-4.0" in page and "not stored" in page and "use_llm" not in page


def test_check_text_returns_json_with_status(db_path):
    c = TestClient(create_app(db_path))
    r = upload(c, "d.txt", b"Ram Lal v. State of Bihar, 1960 INSC 5 held that bail is a right.")
    body = r.json()
    assert r.status_code == 200 and "not legal advice" in body["disclaimer"].lower()
    assert body["citations"][0]["status"] == "VERIFIED"  # exact number, AI check off
    assert body["citations"][0]["case_id"] == "C1"


def test_report_returns_escaped_html(db_path):
    c = TestClient(create_app(db_path))
    r = upload(c, "d<x>.txt", b"See 2099 INSC 9<script>", path="/report")
    assert r.status_code == 200 and "<script>" not in r.text
    assert "NOT_FOUND_IN_CORPUS" in r.text and "&lt;x&gt;" in r.text


def test_docx_upload_works(db_path):
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("Ram Lal v. State of Bihar, 1960 INSC 5.")
    doc.save(buf)
    c = TestClient(create_app(db_path))
    assert upload(c, "d.docx", buf.getvalue()).json()["citations"][0]["case_id"] == "C1"


def test_bad_inputs_are_clean_errors(db_path):
    c = TestClient(create_app(db_path))
    assert upload(c, "d.pdf", b"%PDF").status_code == 400  # corrupt PDF
    assert upload(c, "d.docx", b"not a zip").status_code == 400
    assert upload(c, "d.txt", b"x" * (MAX_UPLOAD_BYTES + 1)).status_code == 413
    many = ("Ram Lal v. State, 1960 INSC 5. " * 70).encode()
    assert upload(c, "d.txt", many).status_code == 413


def test_llm_is_refused_unless_the_operator_enabled_it(db_path):
    c = TestClient(create_app(db_path, llm_enabled=False))
    assert upload(c, "d.txt", b"1960 INSC 5", use_llm="true").status_code == 400
    on = TestClient(create_app(db_path, llm_enabled=True)).get("/").text
    assert "use_llm" in on  # the checkbox appears only when enabled


def test_missing_database_is_503(tmp_path):
    c = TestClient(create_app(tmp_path / "nope.db"))
    assert upload(c, "d.txt", b"1960 INSC 5").status_code == 503


def test_page_assets_are_served_with_a_strict_security_policy(db_path):
    c = TestClient(create_app(db_path))
    page = c.get("/")
    assert "{{" not in page.text  # every placeholder was filled
    assert "1" in page.text and "Try a sample draft" in page.text
    csp = page.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp
    assert "<script>" not in page.text  # no inline script, so the policy can forbid it
    for asset in ("/static/app.css", "/static/app.js", "/static/favicon.svg"):
        assert c.get(asset).status_code == 200
    assert c.get("/static/../app.py").status_code == 404
