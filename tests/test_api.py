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
    assert "1" in page.text and "Run a sample draft" in page.text
    csp = page.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp
    assert "<script>" not in page.text  # no inline script, so the policy can forbid it
    for asset in ("/static/app.css", "/static/app.js", "/static/favicon.svg"):
        assert c.get(asset).status_code == 200
    assert c.get("/static/../app.py").status_code == 404


# --- the reading agent on the web ---
def test_agents_are_off_by_default_and_the_box_is_hidden(db_path):
    c = TestClient(create_app(db_path))
    assert "use_agents" not in c.get("/").text
    r = upload(c, "d.txt", b"1960 INSC 5", use_agents="true")
    assert r.status_code == 400 and "not enabled" in r.json()["detail"]


def test_agent_box_says_what_is_sent_where_when_enabled(db_path):
    page = TestClient(create_app(db_path, agents_enabled=True)).get("/").text
    assert 'name="use_agents"' in page and "Gemini" in page and "never a green tick" in page
    assert "{{AGENT_BOX}}" not in page


def test_agent_run_uses_the_orchestrator_without_a_disk_cache(db_path, monkeypatch):
    seen = {}

    def fake_review(con, text, budget, **kw):
        from pramaan.citations.extract import extract
        from pramaan.pipeline import check_citation

        seen["kw"], seen["budget"] = kw, budget
        return [check_citation(con, c, use_llm=False) for c in extract(text)]

    monkeypatch.setattr("pramaan.api.app.review_text", fake_review)
    c = TestClient(create_app(db_path, agents_enabled=True))
    r = upload(c, "d.txt", b"Ram Lal v. State of Bihar, 1960 INSC 5 held X.", use_agents="true")
    assert r.status_code == 200 and r.json()["agents_used"] is True
    assert seen["kw"] == {"cache": False}  # what a visitor wrote is never saved
    assert seen["budget"].max_agent_calls <= 4 and seen["budget"].max_seconds <= 150


def test_a_second_agent_job_is_told_to_wait_not_queued(db_path, monkeypatch):
    import threading

    started, release = threading.Event(), threading.Event()

    def slow_review(con, text, budget, **kw):
        started.set()
        release.wait(5)
        return []

    monkeypatch.setattr("pramaan.api.app.review_text", slow_review)
    c = TestClient(create_app(db_path, agents_enabled=True))
    results = []
    t = threading.Thread(target=lambda: results.append(
        upload(c, "d.txt", b"1960 INSC 5", use_agents="true")))
    t.start()
    assert started.wait(5)
    second = upload(c, "d.txt", b"1960 INSC 5", use_agents="true")
    release.set()
    t.join()
    assert second.status_code == 503 and "busy" in second.json()["detail"]
    assert results[0].status_code == 200
