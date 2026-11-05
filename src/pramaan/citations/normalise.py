"""Parse a matched citation string into structured fields, and normalise party names.

Parsing regexes are anchored (^...$) since the input is already a span `patterns.py`
matched — they're intentionally stricter than the detection regexes. Party-name stripping
list is the abbreviation set docs/DATA_NOTES.md §3 actually measured in our corpus
(& Ors. 43%, & Anr. 26%, M/s 10%, etc.) — not a generic guess.
"""

import re
import unicodedata

from pydantic import BaseModel


class ParsedCitation(BaseModel):
    reporter: str
    year: int
    volume: int | None
    page: int


# The volume can come before "Supp" ("[1992] 2 Supp. SCR 1"), after it ("[1992] SUPP. 2 S.C.R. 1",
# the dataset's own form) or in brackets after it ("[1992] Supp. (2) SCR 1").
_SCR = re.compile(
    r"^[\[\(]\s*(\d{4})\s*[\]\)]\s*(\d{1,2})?\s*"
    r"(?:(suppl?)\.?\s*(?:\(?(\d{1,2})\)?\s*)?)?"
    r"S\.?\s?C\.?\s?R\.?\s+(\d{1,4})$",
    re.IGNORECASE,
)
_NEUTRAL = re.compile(r"^(\d{4})\s+INSC\s+(\d{1,5})$")
_SCC = re.compile(r"^\(\s*(\d{4})\s*\)\s*(\d{1,2})\s+SCC\s+(\d{1,4})$")
_SCC_ONLINE = re.compile(r"^(\d{4})\s+SCC\s+OnLine\s+SC\s+(\d{1,5})$", re.IGNORECASE)
_AIR = re.compile(r"^AIR\s+(\d{4})\s+SC\s+(\d{1,5})$")


_SCR_YEAR_VOL = re.compile(r"^(\d{4})\s*\((\d{1,2})\)\s*S\.?\s?C\.?\s?R\.?\s+(\d{1,4})$", re.I)


def parse_scr(raw: str) -> ParsedCitation | None:
    alt = _SCR_YEAR_VOL.match(raw.strip())  # "1976 (2) SCR 100"
    if alt:
        return ParsedCitation(
            reporter="SCR", year=int(alt[1]), volume=int(alt[2]), page=int(alt[3])
        )
    m = _SCR.match(raw.strip())
    if not m:
        return None
    year, volume_before, supp, volume_after, page = m.groups()
    volume = volume_after or volume_before
    # The Supplement series restarts its page numbers inside the same year and volume number, so
    # it must never be mixed with the regular series: it gets its own reporter name.
    return ParsedCitation(
        reporter="SCR-SUPP" if supp else "SCR",
        year=int(year),
        volume=int(volume) if volume else None,
        page=int(page),
    )


def parse_neutral(raw: str) -> ParsedCitation | None:
    m = _NEUTRAL.match(raw.strip())
    if not m:
        return None
    year, number = m.groups()
    return ParsedCitation(reporter="INSC", year=int(year), volume=None, page=int(number))


def parse_scc(raw: str) -> ParsedCitation | None:
    m = _SCC.match(raw.strip())
    if not m:
        return None
    year, volume, page = m.groups()
    return ParsedCitation(reporter="SCC", year=int(year), volume=int(volume), page=int(page))


def parse_scc_online(raw: str) -> ParsedCitation | None:
    m = _SCC_ONLINE.match(raw.strip())
    if not m:
        return None
    year, number = m.groups()
    return ParsedCitation(reporter="SCC_ONLINE", year=int(year), volume=None, page=int(number))


def parse_air(raw: str) -> ParsedCitation | None:
    m = _AIR.match(raw.strip())
    if not m:
        return None
    year, page = m.groups()
    return ParsedCitation(reporter="AIR", year=int(year), volume=None, page=int(page))


_PARSERS = {
    "SCR": parse_scr,
    "NEUTRAL": parse_neutral,
    "SCC": parse_scc,
    "SCC_ONLINE": parse_scc_online,
    "AIR": parse_air,
}


def parse_citation(raw: str, format_: str) -> ParsedCitation | None:
    """Dispatch to the right parser for a structured format (not CASE_NAME)."""
    parser = _PARSERS.get(format_)
    return parser(raw) if parser else None


# Measured in docs/DATA_NOTES.md §3 — frequency in real case titles, 2022-2024 metadata.
_PARTY_NAME_STRIP = [
    re.compile(r"\bM/[sS]\.?\b"),
    re.compile(r"&\s*ORS\.?\b"),
    re.compile(r"\bAND\s+ORS\.?\b"),
    re.compile(r"&\s*ANR\.?\b"),
    re.compile(r"\bAND\s+ANR\.?\b"),
    re.compile(r"(?:&|\bAND)\s*OTHERS?\b"),
    re.compile(r"(?:&|\bAND)\s*ANOTHER\b"),
    re.compile(r"\bETC\.?\b"),
    re.compile(r"\(D\)"),
    re.compile(r"\bDECEASED\b"),
    re.compile(r"\bTHR\.?\s*LRS\.?\b"),
    re.compile(r"\bTHROUGH\s+LRS\.?\b"),
]


def normalise_party_name(name: str) -> str:
    """Strip common abbreviations/suffixes, case-fold, and collapse whitespace."""
    text = unicodedata.normalize("NFKC", name).upper()
    for pattern in _PARTY_NAME_STRIP:
        text = pattern.sub("", text)
    text = re.sub(r"[.,]+$", "", text.strip())
    return re.sub(r"\s+", " ", text).strip()
