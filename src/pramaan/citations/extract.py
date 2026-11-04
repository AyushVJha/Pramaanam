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
_QUOTE_TIGHT_GAP = 100  # characters between a quote and its citation

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
    # How sure we are that the name / quote belongs to THIS citation. Loose links (a footnote
    # number or a whole sentence in between) are fine for a tick but too weak for an accusation.
    name_tight: bool = True
    quote_tight: bool = True


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


def _trim_to_name(raw: str) -> tuple[int, str] | None:
    """If the match has sentence words stuck on the front ("The petitioner relies on Maneka
    Gandhi v. Union of India"), drop leading words until a plausible name starting with a
    capital letter is left. Returns (characters dropped, name) or None."""
    left = re.split(r"\s+vs?\.?\s+", raw, maxsplit=1, flags=re.IGNORECASE)[0]
    words = list(re.finditer(r"\S+", left))
    for w in words[1:]:
        candidate = raw[w.start():]
        if w.group(0)[0].isupper() and _is_plausible_case_name(candidate):
            return w.start(), candidate
    return None


def _find_case_name_matches(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in CASE_NAME.finditer(text):
        raw = m.group(0).strip()
        start = m.start()
        if not _is_plausible_case_name(raw):
            trimmed = _trim_to_name(raw)
            if trimmed is None:
                continue
            start, raw = start + trimmed[0], trimmed[1]
        out.append((start, m.end(), raw))
    return out


def _attach_case_names(
    structured: list[tuple[int, int, str, str]], case_names: list[tuple[int, int, str]]
) -> tuple[dict[int, tuple[str, int]], set[int]]:
    """Map each structured match's index to a preceding case name, if close enough."""
    attached: dict[int, tuple[str, int]] = {}  # index -> (name, where the name ends)
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
            attached[i] = (_clean_case_name(best[1]), case_names[best[0]][1])
            used.add(best[0])
    return attached, used


def _proposition(text: str, span: tuple[int, int]) -> str:
    """The sentence(s) containing `span`."""
    start, end = span
    sentence_start = max((m.end() for m in _SENTENCE_SPLIT.finditer(text[:start])), default=0)
    following = _SENTENCE_SPLIT.search(text, end)
    sentence_end = following.start() if following else len(text)
    return text[sentence_start:sentence_end].strip()


def _assign_nearest(
    text: str, pattern: re.Pattern, spans: list[tuple[int, int]], window: int
) -> dict[int, re.Match]:
    """Give each match of `pattern` to the ONE nearest citation span, never across a blank line.

    Before this, every citation took the first match within the window, so a quote could be
    attached to a neighbouring citation and then be checked against the wrong judgment.
    A citation keeps the first (leftmost) match assigned to it.
    """
    owner: dict[int, re.Match] = {}
    for m in pattern.finditer(text):
        best: tuple[int, int] | None = None  # (gap, citation index)
        for i, (start, end) in enumerate(spans):
            gap = max(0, m.start() - end, start - m.end())
            lo, hi = min(m.start(), start), max(m.end(), end)
            if gap <= window and "\n\n" not in text[lo:hi] and (best is None or gap < best[0]):
                best = (gap, i)
        if best is not None and best[1] not in owner:
            owner[best[1]] = m
    return owner


def _name_is_tight(text: str, name_end: int, cite_start: int) -> bool:
    """No digits between the name and the citation: a digit there is usually a footnote marker,
    and then the name may belong to the footnote number, not to this citation."""
    return not re.search(r"\d", text[name_end:cite_start])


def _quote_is_tight(match: re.Match, span: tuple[int, int]) -> bool:
    gap = max(0, match.start() - span[1], span[0] - match.end())
    return gap <= _QUOTE_TIGHT_GAP


def extract(text: str) -> list[Citation]:
    """Find every citation in `text` — structured formats plus standalone case names."""
    structured = _find_structured_matches(text)
    case_names = _find_case_name_matches(text)
    attached_names, used_case_name_idx = _attach_case_names(structured, case_names)

    spans = [(st, en) for st, en, _f, _r in structured] + [
        (st, en) for j, (st, en, _n) in enumerate(case_names) if j not in used_case_name_idx
    ]
    quotes = _assign_nearest(text, _QUOTE, spans, window=200)
    para_refs = _assign_nearest(text, _PARA_REF, spans, window=80)

    def quote_of(k: int) -> str | None:
        return quotes[k].group(1).strip() if k in quotes else None

    def para_of(k: int) -> int | None:
        return int(para_refs[k].group(1)) if k in para_refs else None

    citations = []
    for i, (start, end, fmt, raw) in enumerate(structured):
        span = (start, end)
        citations.append(
            Citation(
                raw=raw,
                span=span,
                format=fmt,
                parsed=parse_citation(raw, fmt),
                case_name=attached_names[i][0] if i in attached_names else None,
                name_tight=i not in attached_names
                or _name_is_tight(text, attached_names[i][1], start),
                quote_tight=i not in quotes or _quote_is_tight(quotes[i], span),
                proposition=_proposition(text, span),
                quoted_text=quote_of(i),
                para_ref=para_of(i),
            )
        )

    k = len(structured)
    for j, (cn_start, cn_end, name) in enumerate(case_names):
        if j in used_case_name_idx:
            continue
        idx, k = k, k + 1
        span = (cn_start, cn_end)
        cleaned_name = _clean_case_name(name)
        citations.append(
            Citation(
                raw=name,
                span=span,
                format="CASE_NAME",
                case_name=cleaned_name,
                quote_tight=idx not in quotes or _quote_is_tight(quotes[idx], span),
                proposition=_proposition(text, span),
                quoted_text=quote_of(idx),
                para_ref=para_of(idx),
            )
        )

    citations.sort(key=lambda c: c.span[0])
    return citations
