"""FastAPI service and one-page demo. (M9)

GET  /          upload page (plain HTML form, no JavaScript)
POST /report    form upload -> the annexure as an HTML page
POST /check     upload -> report as JSON (for programs)
GET  /health    liveness

Safe-by-default for a public host:
- uploads are read in memory / a temp file that is deleted at once; nothing is stored or logged;
- the LLM support check is OFF unless the operator sets PRAMAAN_ENABLE_LLM=1 on the server, and
  even then a visitor must ask for it (it sends judgment paragraphs to the configured model);
- upload size and citations per draft are capped, so one visitor cannot hog the machine.
"""

import html
import logging
import os
import sqlite3
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from pramaan import config
from pramaan.api.ratelimit import RateLimiter
from pramaan.citations.extract import extract
from pramaan.data.draft_reader import SUPPORTED, read_draft
from pramaan.data.fetch_db import ensure_database
from pramaan.pipeline import CitationReport, check_citation
from pramaan.report import DISCLAIMER, render_html, report_to_dicts

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_CITATIONS = 60
RATE_LIMIT = 10  # uploads per client per minute
logger = logging.getLogger(__name__)
ATTRIBUTION = (
    "Judgment data: Supreme Court of India judgments, open dataset licensed CC-BY-4.0 "
    "(github.com/vanga/indian-supreme-court-judgments)."
)

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pramaan: citation check</title>
<style>body{font:16px/1.55 system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem}
button{font:inherit;padding:.5rem 1rem}
.note{background:#f3f4f6;padding:.8rem 1rem;border-radius:6px}
footer{margin-top:2rem;font-size:.85rem;color:#555}</style></head><body>
<h1>Pramaan</h1>
<p>Check the citations in a draft against Supreme Court of India judgments: does the case exist,
does the name match, are the quotes real, is the paragraph right.</p>
<p class="note"><b>Preview.</b> %(disclaimer)s Accuracy is still being measured.</p>
<form method="post" action="/report" enctype="multipart/form-data">
<p><input type="file" name="draft" accept=".txt,.md,.docx,.pdf" required></p>
%(llm_box)s
<p><button type="submit">Check citations</button></p></form>
<p>Your file is read, checked and discarded. It is not stored. Word files: headers, footers
and text boxes are not read. Limits: %(mb)d MB, %(n)d citations.</p>
<footer>%(attribution)s</footer></body></html>"""

LLM_BOX = (
    '<p><label><input type="checkbox" name="use_llm" value="1"> Also run the AI support check '
    "(sends short excerpts of the matched judgment to a language model)</label></p>"
)


def create_app(db_path: Path | None = None, llm_enabled: bool | None = None) -> FastAPI:
    db = db_path or config.DB_PATH
    llm_ok = llm_enabled if llm_enabled is not None else os.environ.get("PRAMAAN_ENABLE_LLM") == "1"
    limiter = RateLimiter(RATE_LIMIT, 60.0)

    def client_of(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")

    def throttle(request: Request) -> None:
        if not limiter.allow(client_of(request)):
            raise HTTPException(429, "Too many uploads; wait a minute and try again.")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:  # download the database on first start of a fresh host
            ensure_database(
                db, os.environ.get("PRAMAAN_DB_URL"), os.environ.get("PRAMAAN_DB_SHA256")
            )
        except Exception:
            logger.exception("could not prepare the database")  # /health will report it
        yield

    app = FastAPI(title="Pramaan", version="0.1.0", lifespan=lifespan)

    def run_check(upload: UploadFile, data: bytes, use_llm: bool) -> list[CitationReport]:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in SUPPORTED:
            raise HTTPException(400, f"Unsupported file type. Use one of: {sorted(SUPPORTED)}")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"File is larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")
        if use_llm and not llm_ok:
            raise HTTPException(400, "The AI support check is not enabled on this server.")
        if not db.exists():
            raise HTTPException(503, "The judgment database is not available.")
        with tempfile.TemporaryDirectory() as tmp:  # deleted as soon as the block ends
            path = Path(tmp) / f"draft{suffix}"
            path.write_bytes(data)
            try:
                text = read_draft(path)
            except Exception as e:  # a corrupt Word file raises several different errors
                raise HTTPException(400, "Could not read that file.") from e
        citations = extract(text)
        if len(citations) > MAX_CITATIONS:
            raise HTTPException(413, f"More than {MAX_CITATIONS} citations; split the draft.")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)  # one connection per request
        try:
            return [check_citation(con, c, use_llm=use_llm) for c in citations]
        finally:
            con.close()

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return PAGE % {
            "disclaimer": html.escape(DISCLAIMER), "llm_box": LLM_BOX if llm_ok else "",
            "mb": MAX_UPLOAD_BYTES // 1024 // 1024, "n": MAX_CITATIONS,
            "attribution": html.escape(ATTRIBUTION),
        }

    @app.post("/report", response_class=HTMLResponse)
    async def report(
        request: Request, draft: UploadFile = File(...), use_llm: str = Form("")
    ) -> str:
        throttle(request)
        data = await draft.read(MAX_UPLOAD_BYTES + 1)
        reports = run_check(draft, data, bool(use_llm))
        model = config.JUDGE_MODEL if use_llm else None
        return render_html(
            reports, source=draft.filename or "draft", date=time.strftime("%Y-%m-%d"),
            llm_used=bool(use_llm), model=model,
        )

    @app.post("/check")
    async def check(
        request: Request, draft: UploadFile = File(...), use_llm: bool = Form(False)
    ) -> dict:
        throttle(request)
        data = await draft.read(MAX_UPLOAD_BYTES + 1)
        reports = run_check(draft, data, use_llm)
        return {
            "date": time.strftime("%Y-%m-%d"), "disclaimer": DISCLAIMER,
            "attribution": ATTRIBUTION, "llm_used": use_llm,
            "citations": report_to_dicts(reports),
        }

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "database": db.exists()}

    return app


app = create_app()
