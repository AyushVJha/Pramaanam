"""Render the per-citation verification report (status table per SPEC.md §4.1). (M5)"""

import html

from pramaan.pipeline import CitationReport


def render_report(reports: list[CitationReport]) -> str:
    if not reports:
        return "No citations found in the draft."
    lines = []
    for i, r in enumerate(reports, 1):
        lines.append(f"{i}. [{r.status}] {r.raw}" + (f"  ({r.case_name})" if r.case_name else ""))
        lines.append(f"   {r.reason}")
        if r.case_title:
            lines.append(f"   Matched: {r.case_title} ({r.case_year}) id={r.case_id}")
        if r.support and r.support.evidence:
            for ev in r.support.evidence:
                lines.append(f"   Evidence, para {ev.para_no}: \"{ev.quote}\"")
        lines.append("")
    counts: dict[str, int] = {}
    for r in reports:
        counts[r.status] = counts.get(r.status, 0) + 1
    summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
    cost = sum(r.cost_usd for r in reports)
    lines.append(f"{len(reports)} citations: {summary}. LLM cost: ${cost:.4f}")
    lines.append("This tool reports evidence. A lawyer decides.")
    return "\n".join(lines)


# ---- Annexure: a report a lawyer can keep, file or hand to a client (Markdown / HTML / JSON) ----

DISCLAIMER = (
    "Automated check, not legal advice. Verify against an authorised source. "
    "A status of NOT_FOUND_IN_CORPUS does not mean a case is fake: the corpus holds Supreme Court "
    "of India judgments only (CC-BY-4.0 open dataset) and misses High Court cases and "
    "commercial-only citations."
)

STATUS_MEANING = {
    "VERIFIED": "Found, name and year match, quotes found, judgment supports the proposition.",
    "NOT_FOUND_IN_CORPUS": "No matching judgment in the corpus. Not a finding that it is fake.",
    "NAME_MISMATCH": "The citation resolves to a different case than the name given.",
    "MISQUOTE": "Quoted words were not found in the judgment.",
    "WRONG_PARAGRAPH": "The content exists but not at the cited paragraph.",
    "UNSUPPORTED": "The judgment does not appear to support the proposition.",
    "CONTRADICTED": "The judgment appears to say the opposite of the proposition.",
    "NEEDS_REVIEW": "Low confidence or a check was not run. A person must look.",
}


def report_to_dicts(reports: list[CitationReport]) -> list[dict]:
    return [r.model_dump() for r in reports]


def _method_line(llm_used: bool, model: str | None) -> str:
    if not llm_used:
        return "Checks run: existence, identity, quotes, paragraph. Support check: not run."
    return f"Checks run: existence, identity, quotes, paragraph, support (model: {model})."


def render_markdown(
    reports: list[CitationReport], source: str, date: str, *, llm_used: bool, model: str | None
) -> str:
    lines = [
        "# Citation verification annexure",
        "",
        f"Draft: {source}  |  Date: {date}  |  Citations checked: {len(reports)}",
        "",
        f"> {DISCLAIMER}",
        "",
        _method_line(llm_used, model),
        "",
        "| # | Citation | Status | Matched judgment | Note |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(reports, 1):
        matched = f"{r.case_title} ({r.case_year}) [{r.case_id}]" if r.case_title else "-"
        cell = lambda t: str(t).replace("|", "\\|").replace("\n", " ")  # noqa: E731
        lines.append(f"| {i} | {cell(r.raw)} | {r.status} | {cell(matched)} | {cell(r.reason)} |")
    evidence = [(i, r) for i, r in enumerate(reports, 1) if r.support and r.support.evidence]
    if evidence:
        lines += ["", "## Evidence quoted from the judgments", ""]
        for i, r in evidence:
            for ev in r.support.evidence:
                lines.append(f"- {i}. para {ev.para_no}: \"{ev.quote}\"")
    lines += ["", "## What the statuses mean", ""]
    lines += [f"- **{s}**: {m}" for s, m in STATUS_MEANING.items()]
    return "\n".join(lines) + "\n"


def render_html(
    reports: list[CitationReport], source: str, date: str, *, llm_used: bool, model: str | None
) -> str:
    esc = html.escape
    rows = []
    for i, r in enumerate(reports, 1):
        matched = f"{r.case_title} ({r.case_year}) [{r.case_id}]" if r.case_title else "-"
        rows.append(
            f"<tr><td>{i}</td><td>{esc(r.raw)}</td><td class='s-{esc(r.status)}'>{esc(r.status)}"
            f"</td><td>{esc(matched)}</td><td>{esc(r.reason)}</td></tr>"
        )
    evidence = "".join(
        f"<li>{i}. para {ev.para_no}: &ldquo;{esc(ev.quote)}&rdquo;</li>"
        for i, r in enumerate(reports, 1) if r.support
        for ev in r.support.evidence
    )
    legend = "".join(f"<li><b>{s}</b>: {esc(m)}</li>" for s, m in STATUS_MEANING.items())
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Citation verification annexure</title>"
        "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;"
        "padding:0 1rem}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;"
        "padding:.4rem;text-align:left;vertical-align:top}.s-VERIFIED{color:#166534}"
        ".s-NOT_FOUND_IN_CORPUS,.s-NEEDS_REVIEW{color:#92400e}.s-NAME_MISMATCH,.s-MISQUOTE,"
        ".s-WRONG_PARAGRAPH,.s-UNSUPPORTED,.s-CONTRADICTED{color:#991b1b}"
        "blockquote{border-left:4px solid #bbb;margin:1rem 0;padding:.2rem 1rem}</style></head>"
        f"<body><h1>Citation verification annexure</h1><p>Draft: {esc(source)} &nbsp;|&nbsp; "
        f"Date: {esc(date)} &nbsp;|&nbsp; Citations checked: {len(reports)}</p>"
        f"<blockquote>{esc(DISCLAIMER)}</blockquote><p>{esc(_method_line(llm_used, model))}</p>"
        "<table><tr><th>#</th><th>Citation</th><th>Status</th><th>Matched judgment</th>"
        f"<th>Note</th></tr>{''.join(rows)}</table>"
        + (f"<h2>Evidence quoted from the judgments</h2><ul>{evidence}</ul>" if evidence else "")
        + f"<h2>What the statuses mean</h2><ul>{legend}</ul></body></html>"
    )
