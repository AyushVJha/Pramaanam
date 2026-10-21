"""Extract Citation objects from draft text. (SPEC.md §4 step 1)

Each has raw, span, format, parsed fields, case_name, proposition, quoted_text, para_ref.

Case-name-only mentions use regex + heuristic filtering only (no LLM fallback yet — SPEC.md
§4 step 1 calls for one, but llm/client.py doesn't exist until M5; filed as a precision gap
rather than blocking M2 on building that infrastructure early).
"""

import re

from pydantic import BaseModel

from pramaan.citations.normalise import ParsedCitation, parse_citation
from pramaan.citations.patterns import CASE_NAME, STRUCTURED

# How far back from a structured citation to look for an attached case name, e.g.
# "Bhanu Kumar Jain vs. Archana Kumar, AIR 2005 SC 626" — the name precedes the citation.
_CASE_NAME_PROXIMITY = 40

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_QUOTE = re.compile(r"[\"“]([^\"“”]{15,}?)[\"”]")
_PARA_REF = re.compile(r"\bpara(?:graph)?s?\.?\s*(?:no\.?\s*)?(\d{1,4})\b", re.IGNORECASE)

# Minimum word count on each side of "v."/"vs." to count as a case name, not a stray phrase.
_MIN_NAME_WORDS = 1

# Common Indian legal-writing lead-ins before a case name, stripped from the reported name
# (not from the matched span) so "In Bhanu Kumar Jain v. X" reports just "Bhanu Kumar Jain v. X".
_LEADING_WORDS = re.compile(
    r"^(?:In\s+Re:?\s+|In\s+|See\s+|Vide\s+|Per\s+|Court\s+in\s+|Bench\s+in\s+)",
    re.IGNORECASE,
)


def _clean_case_name(raw: str) -> str:
    return _LEADING_WORDS.sub("", raw).strip()


class Citation(BaseModel):
    raw: str
    span: tuple[int, int]
    format: str  # one of patterns.STRUCTURED's keys, or "CASE_NAME"
    parsed: ParsedCitation | None = None
    case_name: str | None = None
    proposition: str
    quoted_text: str | None = None
    para_ref: int | None = None


def _find_structured_matches(text: str) -> list[tuple[int, int, str, str]]:
    """All non-overlapping structured-format matches, as (start, end, format, raw)."""
    matches: list[tuple[int, int, str, str]] = []
    for fmt, pattern in STRUCTURED.items():
        for m in pattern.finditer(text):
            matches.append((m.start(), m.end(), fmt, m.group(0)))
    matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))

    deduped: list[tuple[int, int, str, str]] = []
    last_end = -1
    for start, end, fmt, raw in matches:
        if start >= last_end:
            deduped.append((start, end, fmt, raw))
            last_end = end
    return deduped


# Common connectors that are legitimately lowercase inside a real party name
# ("State of Bihar", "Union of India and Ors.") — excluded before judging capitalisation.
_CONNECTOR_WORDS = {
    "of", "and", "the", "in", "on", "for", "to", "or", "at", "by", "as",
    "is", "was", "that", "this", "&",
}
_MIN_CAP_RATIO = 0.6


def _capitalised_ratio(words: list[str]) -> float:
    significant = [w for w in words if w.lower().strip(".,'-") not in _CONNECTOR_WORDS and w]
    if not significant:
        return 0.0
    capped = sum(1 for w in significant if w[0].isupper())
    return capped / len(significant)


def _is_plausible_case_name(raw: str) -> bool:
    """Filters the high-recall CASE_NAME regex match down to names that actually look like
    names — mostly-capitalised on both sides, not a sentence fragment that happened to end
    in "... v. ..." (e.g. "the decision of this Court in X v. Y" should pass; "Reliance was
    placed on the decision of this Court in" should not, and is rejected by its low
    capitalised-word ratio).
    """
    parts = re.split(r"\s+vs?\.?\s+", raw, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return False
    left, right = parts
    left_words, right_words = left.split(), right.split()
    if len(left_words) < _MIN_NAME_WORDS or len(right_words) < _MIN_NAME_WORDS:
        return False
    return (
        _capitalised_ratio(left_words) >= _MIN_CAP_RATIO
        and _capitalised_ratio(right_words) >= _MIN_CAP_RATIO
    )


def _find_case_name_matches(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in CASE_NAME.finditer(text):
        raw = m.group(0).strip()
        if _is_plausible_case_name(raw):
            out.append((m.start(), m.end(), raw))
    return out


def _attach_case_names(
    structured: list[tuple[int, int, str, str]], case_names: list[tuple[int, int, str]]
) -> tuple[dict[int, str], set[int]]:
    """Map each structured match's index to a preceding case name, if close enough."""
    attached: dict[int, str] = {}
    used: set[int] = set()
    for i, (start, _end, _fmt, _raw) in enumerate(structured):
        best = None
        for j, (_cn_start, cn_end, name) in enumerate(case_names):
            if j in used:
                continue
            gap = start - cn_end
            if 0 <= gap <= _CASE_NAME_PROXIMITY:
                best = (j, name)
        if best:
            attached[i] = _clean_case_name(best[1])
            used.add(best[0])
    return attached, used


def _proposition(text: str, span: tuple[int, int]) -> str:
    """The sentence(s) containing `span`."""
    start, end = span
    sentence_start = max((m.end() for m in _SENTENCE_SPLIT.finditer(text[:start])), default=0)
    following = _SENTENCE_SPLIT.search(text, end)
    sentence_end = following.start() if following else len(text)
    return text[sentence_start:sentence_end].strip()


def _nearby_quote(text: str, span: tuple[int, int], window: int = 200) -> str | None:
    start, end = span
    region = text[max(0, start - window) : min(len(text), end + window)]
    m = _QUOTE.search(region)
    return m.group(1).strip() if m else None


def _nearby_para_ref(text: str, span: tuple[int, int], window: int = 80) -> int | None:
    start, end = span
    region = text[max(0, start - window) : min(len(text), end + window)]
    m = _PARA_REF.search(region)
    return int(m.group(1)) if m else None


def extract(text: str) -> list[Citation]:
    """Find every citation in `text` — structured formats plus standalone case names."""
    structured = _find_structured_matches(text)
    case_names = _find_case_name_matches(text)
    attached_names, used_case_name_idx = _attach_case_names(structured, case_names)

    citations = []
    for i, (start, end, fmt, raw) in enumerate(structured):
        span = (start, end)
        citations.append(
            Citation(
                raw=raw,
                span=span,
                format=fmt,
                parsed=parse_citation(raw, fmt),
                case_name=attached_names.get(i),
                proposition=_proposition(text, span),
                quoted_text=_nearby_quote(text, span),
                para_ref=_nearby_para_ref(text, span),
            )
        )

    for j, (cn_start, cn_end, name) in enumerate(case_names):
        if j in used_case_name_idx:
            continue
        span = (cn_start, cn_end)
        cleaned_name = _clean_case_name(name)
        citations.append(
            Citation(
                raw=name,
                span=span,
                format="CASE_NAME",
                case_name=cleaned_name,
                proposition=_proposition(text, span),
                quoted_text=_nearby_quote(text, span),
                para_ref=_nearby_para_ref(text, span),
            )
        )

    citations.sort(key=lambda c: c.span[0])
    return citations
