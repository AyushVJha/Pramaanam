"""Render the per-citation verification report (status table per SPEC.md §4.1). (M5)"""

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
