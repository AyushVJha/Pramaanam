"""Wire extract -> normalise -> resolve -> identity -> quote -> paragraph -> support. (M5)

check_citation() runs the checks in SPEC order and stops being "VERIFIED" at the first problem.
The status words are exactly those of SPEC 4.1. "Not found" is never called "fake".
"""

import sqlite3
from typing import Literal

from pydantic import BaseModel

from pramaan.checks.identity import IdentityResult, check_identity
from pramaan.checks.paragraph import ParagraphResult, check_paragraph
from pramaan.checks.quotes import QuoteResult, check_quote
from pramaan.checks.support import SupportResult, check_support
from pramaan.citations.extract import Citation, extract
from pramaan.llm.client import Backend
from pramaan.resolve.names import DECISION_YEAR_SQL
from pramaan.resolve.resolver import Resolution, resolve

Status = Literal[
    "VERIFIED", "NOT_FOUND_IN_CORPUS", "NAME_MISMATCH", "MISQUOTE", "WRONG_PARAGRAPH",
    "UNSUPPORTED", "CONTRADICTED", "NEEDS_REVIEW",
]


class CitationReport(BaseModel):
    raw: str
    case_name: str | None
    status: Status
    reason: str  # one sentence a lawyer can read
    case_id: str | None = None
    case_title: str | None = None
    case_year: int | None = None
    resolution: Resolution
    identity: IdentityResult | None = None
    quote: QuoteResult | None = None
    paragraph: ParagraphResult | None = None
    support: SupportResult | None = None
    cost_usd: float = 0.0


def _case_info(con: sqlite3.Connection, case_id: str) -> tuple[str | None, int | None]:
    row = con.execute(
        f"SELECT title, {DECISION_YEAR_SQL} FROM cases c WHERE c.cnr = ?", (case_id,)
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def check_citation(
    con: sqlite3.Connection,
    citation: Citation,
    *,
    use_llm: bool = True,
    model: str | None = None,
    backend: Backend | None = None,
    **client_kw,
) -> CitationReport:
    base = {"raw": citation.raw, "case_name": citation.case_name}
    resolution = resolve(con, citation)

    if resolution.case_id is None:
        if resolution.method == "ambiguous":
            return CitationReport(
                **base, status="NEEDS_REVIEW", resolution=resolution,
                reason="The citation number matches more than one judgment; not guessing.",
            )
        return CitationReport(
            **base, status="NOT_FOUND_IN_CORPUS", resolution=resolution,
            reason="No matching judgment in the corpus. This does not mean the case is fake: "
            "it may be a High Court case, or use a reporter this dataset does not index.",
        )

    case_id = resolution.case_id
    title, year = _case_info(con, case_id)
    found = {**base, "resolution": resolution, "case_id": case_id,
             "case_title": title, "case_year": year}

    draft_year = citation.parsed.year if citation.parsed else None
    identity = check_identity(con, case_id, citation.case_name, draft_year)
    found["identity"] = identity
    if identity.verdict == "name_mismatch":
        return CitationReport(**found, status="NAME_MISMATCH", reason=identity.explanation)
    if identity.verdict == "year_mismatch":
        return CitationReport(**found, status="NEEDS_REVIEW", reason=identity.explanation)

    if citation.quoted_text:
        quote = check_quote(con, case_id, citation.quoted_text)
        found["quote"] = quote
        if quote.status == "not_found":
            return CitationReport(
                **found, status="MISQUOTE",
                reason="The quoted words were not found in the judgment.",
            )
        if quote.status == "near_match":
            # Provisional: whether near matches count as misquotes is decided in M7.
            changes = "; ".join(quote.changes) or "wording differs slightly"
            return CitationReport(
                **found, status="NEEDS_REVIEW",
                reason=f"The quote is close but not exact: {changes}.",
            )
        if quote.status == "verbatim":
            paragraph = check_paragraph(citation.para_ref, quote)
            found["paragraph"] = paragraph
            if paragraph.status == "wrong_paragraph":
                return CitationReport(
                    **found, status="WRONG_PARAGRAPH", reason=paragraph.explanation
                )

    if not use_llm:
        return CitationReport(
            **found, status="NEEDS_REVIEW",
            reason="Case found and checks passed; the support check was not run.",
        )

    support = check_support(
        con, case_id, citation.proposition, model=model, backend=backend, **client_kw
    )
    found["support"] = support
    found["cost_usd"] = support.cost_usd
    table: dict[str, tuple[Status, str]] = {
        "supported": ("VERIFIED", "It supports the proposition."),
        "partially_supported": ("NEEDS_REVIEW", "It supports only part of the proposition."),
        "not_supported": ("UNSUPPORTED", "It does not appear to support the proposition."),
        "contradicted": ("CONTRADICTED", "It appears to say the opposite."),
        "cannot_determine": ("NEEDS_REVIEW", "The support check could not decide."),
    }
    status, reason = table[support.verdict]
    return CitationReport(**found, status=status, reason=f"{reason} {support.reason}".strip())


def check_text(con: sqlite3.Connection, text: str, **kw) -> list[CitationReport]:
    return [check_citation(con, c, **kw) for c in extract(text)]
