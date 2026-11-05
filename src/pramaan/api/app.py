"""FastAPI service and one-page demo. (M9)

GET  /          the web page (static/index.html; works without JavaScript as a plain form)
GET  /static/*  its stylesheet, script and icon (no third-party requests)
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
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

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

STATIC = Path(__file__).parent / "static"
# A strict policy is possible because the page loads nothing from other sites and has no inline
# script. Inline styles are allowed only because the downloadable annexure carries its own CSS.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _case_count(db: Path) -> str:
    """'38,397' for the page, read once from the database; a plain phrase if it is missing."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return f"{con.execute('SELECT COUNT(*) FROM cases').fetchone()[0]:,}"
        finally:
            con.close()
    except sqlite3.Error:
        return "Thousands of"


LLM_BOX = (
    '<label class="llm"><input type="checkbox" name="use_llm" value="1"> Also run the AI support '
    "check (sends short excerpts of the matched judgment to a language model; it can only lower a "
    "result, never raise it)</label>"
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

    app = FastAPI(title="Pramaanam", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    page_cache: dict[str, str] = {}

    def page() -> str:
        if "html" not in page_cache:  # the database may arrive after start-up; count it then
            if not db.exists():
                return _render_page("Thousands of", llm_ok)
            page_cache["html"] = _render_page(_case_count(db), llm_ok)
        return page_cache["html"]

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
        return page()

    @app.post("/report", response_class=HTMLResponse)
    async def report(
        request: Request, draft: UploadFile = File(...), use_llm: str = Form("")
    ) -> str:
        throttle(request)
        data = await draft.read(MAX_UPLOAD_BYTES + 1)
        reports = await run_in_threadpool(run_check, draft, data, bool(use_llm))
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
        reports = await run_in_threadpool(run_check, draft, data, use_llm)
        return {
            "date": time.strftime("%Y-%m-%d"), "disclaimer": DISCLAIMER,
            "attribution": ATTRIBUTION, "llm_used": use_llm,
            "citations": report_to_dicts(reports),
        }

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "database": db.exists()}

    return app


def _render_page(cases: str, llm_ok: bool) -> str:
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    values = {
        "{{CASES}}": html.escape(cases), "{{LLM_BOX}}": LLM_BOX if llm_ok else "",
        "{{MB}}": str(MAX_UPLOAD_BYTES // 1024 // 1024), "{{N}}": str(MAX_CITATIONS),
        "{{ATTRIBUTION}}": html.escape(ATTRIBUTION),
    }
    for key, value in values.items():
        text = text.replace(key, value)
    return text


app = create_app()
