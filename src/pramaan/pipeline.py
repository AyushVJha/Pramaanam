"""Wire extract -> normalise -> resolve -> identity -> quote -> paragraph -> support.

The rule that decides everything here: a green tick needs deterministic proof, and the AI check
can only take a tick away, never give one.

  VERIFIED   existence and identity are PROVEN (an exact citation number, or a parallel-citation
             pair printed in at least two other judgments), the name and year agree, and every
             quote is word-for-word in the judgment at the cited place. It does NOT say the
             judgment supports the legal proposition: that is the AI second opinion, shown apart.
  warnings   MISQUOTE, WRONG_PARAGRAPH, NAME_MISMATCH, UNSUPPORTED, CONTRADICTED are only asserted
             when the case itself is proven. If the case was found by name or by a single other
             judgment's parallel citation, the same problem is reported as NEEDS_REVIEW.
  noisy text a quote that matches except for scan-like misreadings is LOW_FIDELITY_SOURCE, not a
             misquote.

The status words are those of SPEC 4.1 plus LOW_FIDELITY_SOURCE and CANNOT_VERIFY.
"Not found" is never called "fake". See docs/CLAIM_CONTRACT.md.
"""

import sqlite3
from typing import Literal

from pydantic import BaseModel

from pramaan.checks.identity import IdentityResult, check_identity
from pramaan.checks.paragraph import ParagraphResult, check_paragraph
from pramaan.checks.quotes import QuoteResult, check_quote
from pramaan.checks.second_reading import second_reading
from pramaan.checks.support import SupportResult, check_support
from pramaan.citations.extract import Citation, extract
from pramaan.llm.client import Backend
from pramaan.resolve.names import DECISION_YEAR_SQL
from pramaan.resolve.resolver import Resolution, resolve

Status = Literal[
    "VERIFIED", "NOT_FOUND_IN_CORPUS", "NAME_MISMATCH", "MISQUOTE", "WRONG_PARAGRAPH",
    "UNSUPPORTED", "CONTRADICTED", "LOW_FIDELITY_SOURCE", "CANNOT_VERIFY", "NEEDS_REVIEW",
]

MIN_ALIAS_WITNESSES = 2  # a parallel-citation pair must be printed in this many other judgments


class CitationReport(BaseModel):
    raw: str
    case_name: str | None
    status: Status
    reason: str  # one sentence a lawyer can read
    case_id: str | None = None
    case_title: str | None = None
    case_year: int | None = None
    resolution: Resolution
    case_proven: bool = False  # the number itself found the case (see is_proven)
    identity: IdentityResult | None = None
    quote: QuoteResult | None = None
    paragraph: ParagraphResult | None = None
    support: SupportResult | None = None  # the AI second opinion; never raises a status
    cost_usd: float = 0.0


def is_proven(resolution: Resolution) -> bool:
    """True when the citation NUMBER led to this case, so a failed check is the draft's fault.

    Exact neutral or SCR numbers prove it. An SCC/AIR number resolved through the alias table
    counts only when at least MIN_ALIAS_WITNESSES other judgments print the same pair (one
    judgment can contain a typo, DATA_NOTES 15). A match on party names alone proves nothing.
    """
    if resolution.method in ("neutral", "reporter"):
        return True
    if resolution.method == "alias":
        return (resolution.witnesses or 0) >= MIN_ALIAS_WITNESSES
    return False


def _weak_reason(resolution: Resolution) -> str:
    if resolution.method == "alias":
        n = resolution.witnesses or 0
        return (
            f"The case was found through a parallel citation printed in {n} other "
            f"judgment{'s' if n != 1 else ''}, not by the citation number itself."
        )
    return "The case was found by its party names only; the citation number did not match."


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
    exclude_citing: str | None = None,  # benchmark use: hide the judgment that built the item
    **client_kw,
) -> CitationReport:
    base = {"raw": citation.raw, "case_name": citation.case_name}
    resolution = resolve(con, citation, exclude_citing=exclude_citing)

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
    proven = is_proven(resolution)
    found = {**base, "resolution": resolution, "case_id": case_id, "case_title": title,
             "case_year": year, "case_proven": proven}
    weak = "" if proven else _weak_reason(resolution)

    def warn(status: Status, reason: str, linked: bool = True, what: str = "") -> CitationReport:
        """A negative finding. Only asserted when the case is proven by its number AND the
        draft's name / quote is clearly tied to this citation; otherwise a person must look."""
        if proven and linked:
            return CitationReport(**found, status=status, reason=reason)
        why = weak if not proven else (
            f"It is not clear that the {what} in the draft belongs to this citation "
            "(a footnote number or a long stretch of text sits between them)."
        )
        return CitationReport(
            **found, status="NEEDS_REVIEW", reason=f"Possible {status}: {reason} {why}"
        )

    draft_year = citation.parsed.year if citation.parsed else None
    identity = check_identity(con, case_id, citation.case_name, draft_year)
    found["identity"] = identity
    if identity.verdict == "name_mismatch":
        return warn("NAME_MISMATCH", identity.explanation, citation.name_tight, "case name")
    if identity.verdict in ("year_mismatch", "name_partial"):
        return CitationReport(**found, status="NEEDS_REVIEW", reason=identity.explanation)

    if citation.quoted_text:
        quote = check_quote(con, case_id, citation.quoted_text)
        found["quote"] = quote
        if quote.status == "not_found":
            other = second_reading(con, case_id, citation.quoted_text)
            if other is not None and other.status != "not_found":
                return CitationReport(
                    **found, status="NEEDS_REVIEW",
                    reason="The quote is missing from the PDF's embedded text but appears in a "
                    "second reading of the page images. The source text is unreliable here; "
                    "compare with the printed page.",
                )
            note = " (checked in two independent readings)" if other is not None else ""
            return warn(
                "MISQUOTE", f"The quoted words were not found in the judgment{note}.",
                citation.quote_tight, "quotation",
            )
        if quote.status == "near_match":
            changes = "; ".join(quote.changes) or "wording differs slightly"
            if quote.noise_like and not quote.flags:
                return CitationReport(
                    **found, status="LOW_FIDELITY_SOURCE",
                    reason=f"The quote matches except for what looks like scan noise ({changes}). "
                    "The text of this judgment is not reliable enough to call it exact or a "
                    "misquote; compare with the printed page.",
                )
            return CitationReport(
                **found, status="NEEDS_REVIEW",
                reason=f"The quote is close but not exact: {changes}.",
            )
        if quote.status == "verbatim":
            paragraph = check_paragraph(citation.para_ref, quote)
            found["paragraph"] = paragraph
            if paragraph.status == "wrong_paragraph":
                return warn(
                    "WRONG_PARAGRAPH", paragraph.explanation, citation.quote_tight, "quotation"
                )

    if use_llm:
        support = check_support(
            con, case_id, citation.proposition, model=model, backend=backend, **client_kw
        )
        found["support"] = support
        found["cost_usd"] = support.cost_usd
        # The AI can only take a tick away. A warning needs its evidence quotes to have been
        # verified inside check_support (otherwise the verdict is cannot_determine).
        if support.verdict == "contradicted":
            return warn(
                "CONTRADICTED", f"AI check: it appears to say the opposite. {support.reason}"
            )
        if support.verdict == "not_supported":
            return warn(
                "UNSUPPORTED", f"AI check: it does not appear to support it. {support.reason}"
            )
        if support.verdict == "partially_supported":
            return CitationReport(
                **found, status="NEEDS_REVIEW",
                reason=f"AI check: it supports only part of the proposition. {support.reason}",
            )

    if not proven:
        if resolution.method == "fuzzy" and citation.parsed is not None:
            reason = (
                "The citation number matches no judgment, but a judgment with a very similar "
                "name exists (shown below). Check the number, or that this is the case meant."
            )
        else:
            reason = f"Found, and no problem detected, but not proven to be the cited case. {weak}"
        return CitationReport(**found, status="NEEDS_REVIEW", reason=reason)
    checked = (
        "The case exists, name and year match" + (", the quote is verbatim" if citation.quoted_text
                                                  else "") + ". "
    )
    ai = {
        "supported": "AI check: it supports the proposition (read it yourself).",
        "cannot_determine": "AI check could not decide on the proposition.",
    }
    tail = (
        ai.get(found["support"].verdict, "") if use_llm
        else "The proposition was not checked (AI check off)."
    )
    return CitationReport(
        **found, status="VERIFIED", reason=f"{checked}This is not a check of your argument. {tail}"
    )


def check_text(con: sqlite3.Connection, text: str, **kw) -> list[CitationReport]:
    return [check_citation(con, c, **kw) for c in extract(text)]
