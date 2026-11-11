"""An MCP server so other AI assistants can verify Indian Supreme Court citations with Pramaan.

Any MCP-capable assistant (Claude Desktop, Cursor, ...) can call these tools before it states a
citation to a user. Only the deterministic checks run: no model call, no network, no cost. The
answers keep the same status words and the same promise as the web page (docs/CLAIM_CONTRACT.md):
VERIFIED means the number proves the judgment, name and year agree and any quote is word-for-word.
It never means "the law says this". NOT_FOUND_IN_CORPUS never means "fake".

Run (stdio):  uv run --extra mcp python -m pramaan.mcp_server
"""

import sqlite3

from mcp.server.mcpserver import MCPServer

from pramaan import config
from pramaan.pipeline import CitationReport, check_text

MAX_CHARS = 60_000
MAX_CITATIONS = 100

INSTRUCTIONS = (
    "Verifies citations to Supreme Court of India judgments against the Court's own open "
    "judgments. Call verify_citations on any text that cites cases, or verify_quote for one "
    "quotation. Report each status as returned. NOT_FOUND_IN_CORPUS does not mean the case is "
    "fake, and VERIFIED does not mean the judgment supports the argument."
)

mcp = MCPServer("pramaan", instructions=INSTRUCTIONS)


def summarise(report: CitationReport) -> dict:
    """The few fields an assistant needs; the full report stays on the web page and CLI."""
    out = {
        "citation": report.raw,
        "case_name_in_text": report.case_name,
        "status": report.status,
        "reason": report.reason,
        "judgment": report.case_title,
        "year": report.case_year,
        "proven_by_citation_number": report.case_proven,
    }
    if report.treatments:
        out["later_treatment"] = [
            {"label": t.label, "by": t.citing_title, "year": t.citing_year}
            for t in report.treatments
        ]
    return out


def run_check(con: sqlite3.Connection, text: str) -> dict:
    if len(text) > MAX_CHARS:
        return {"error": f"text is longer than {MAX_CHARS} characters; send it in parts"}
    reports = check_text(con, text, use_llm=False)
    if len(reports) > MAX_CITATIONS:
        return {"error": f"more than {MAX_CITATIONS} citations; send fewer at a time"}
    return {"citations_found": len(reports), "results": [summarise(r) for r in reports]}


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)


@mcp.tool()
def verify_citations(text: str) -> dict:
    """Check every Supreme Court of India citation in `text` (a paragraph or a whole draft).

    For each citation: does the number identify a real judgment, does the case name agree, and
    is any quoted passage word-for-word in it. Also notes if a later judgment's headnote marks
    the case overruled. Does not judge whether the case supports the argument.
    """
    con = _connect()
    try:
        return run_check(con, text)
    finally:
        con.close()


@mcp.tool()
def verify_quote(case_name: str, citation: str, quote: str) -> dict:
    """Check one quotation: is `quote` word-for-word in the judgment `case_name`, `citation`?

    Example: case_name "Maneka Gandhi v. Union of India", citation "(1978) 1 SCC 248".
    """
    con = _connect()
    try:
        result = run_check(con, f'{case_name}, {citation}: "{quote}"')
    finally:
        con.close()
    if "results" in result and not result["results"]:
        return {"error": "no citation could be read from the case name and citation given"}
    return result


if __name__ == "__main__":
    mcp.run()
