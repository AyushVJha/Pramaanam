"""Fuzzy-match quoted passages against the resolved judgment's paragraphs. (M4, SPEC 4.5)

Both texts are reduced to lowercase words first, so quote marks, dashes, hyphenation and
spacing never decide the answer. Then, in order:
1. word-for-word: the quote appears inside a paragraph, or runs across a break between two
   neighbouring paragraphs;
2. near match: shared four-word runs locate the best-aligned stretch, rapidfuzz scores how many
   words agree, and the differing words are listed, with a flag when a negation or a number changed;
3. otherwise not found.

A quote with "...." in it is checked piece by piece, since courts use it to skip text.
A quote made from two distant paragraphs matches neither one whole, so it is not found.
"""

import difflib
import re
import sqlite3
import unicodedata
from typing import Literal

from pydantic import BaseModel
from rapidfuzz import fuzz

# Tuned on the dev set only and never on test (CLAUDE.md hard rule).
NEAR_THRESHOLD = 85.0  # word-level agreement, 0-100; chosen on dev (bench/tune_quotes.py)
MIN_SEGMENT_WORDS = 4  # shorter pieces ("...the Act...") match almost anywhere
MAX_PARA_HITS = 5
NEGATIONS = {"not", "no", "never", "neither", "nor", "cannot", "without", "none", "nothing"}

_ELLIPSIS = re.compile(r"\.{2,}|…|(?:\.\s){2,}\.")
_WORD = re.compile(r"\w+")


class QuoteResult(BaseModel):
    status: Literal["verbatim", "near_match", "not_found", "too_short"]
    similarity: float  # 0-1, of the weakest piece of the quote
    para_nos: list[int] = []  # paragraphs holding the first piece, best first
    spans_paragraphs: bool = False  # true if a piece runs across two neighbouring paragraphs
    matched_text: str | None = None  # the judgment's own words (lowercased) for the first piece
    changes: list[str] = []  # e.g. ["your quote has 'not', the judgment has 'now'"]
    flags: list[str] = []  # "negation", "number"
    # True when every difference is a single word that looks like a misread of the same word
    # (scan/OCR noise), with no negation or number involved. Used to avoid calling noise a misquote.
    noise_like: bool = False


def normalise(text: str) -> str:
    """Lowercase words only: no punctuation, quote style or spacing."""
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", text).lower()))


def split_segments(quote: str) -> list[str]:
    """Pieces of a quote separated by '...'; pieces under MIN_SEGMENT_WORDS are dropped."""
    pieces = (normalise(p) for p in _ELLIPSIS.split(quote))
    return [p for p in pieces if len(p.split()) >= MIN_SEGMENT_WORDS]


WORD_NOISE_SIMILARITY = 60.0  # letter-level similarity (0-100) of two words that may be one word


def _describe_changes(quote: str, found: str) -> tuple[list[str], list[str], bool]:
    """Word-level differences between the quote and the judgment's words, plus flags.

    The third value says whether every difference could be scan noise: one word replaced by a
    word that shares most of its letters ("settle" / "settll"), and no negation or number.
    """
    a, b = quote.split(), found.split()
    changes: list[str] = []
    flags: set[str] = set()
    noise_like = True
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        mine, theirs = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if not theirs:
            changes.append(f"your quote has '{mine}', which is not in the judgment here")
        elif not mine:
            changes.append(f"the judgment has '{theirs}' here, which your quote leaves out")
        else:
            changes.append(f"your quote has '{mine}', the judgment has '{theirs}'")
        changed = set(a[i1:i2]) | set(b[j1:j2])
        if changed & NEGATIONS:
            flags.add("negation")
        if any(w.isdigit() for w in changed):
            flags.add("number")
        one_for_one = op == "replace" and i2 - i1 == 1 and j2 - j1 == 1
        if not (one_for_one and fuzz.ratio(mine, theirs) >= WORD_NOISE_SIMILARITY):
            noise_like = False
    return changes, sorted(flags), noise_like and not flags


class _Hit(BaseModel):
    score: float  # 0-100
    para_no: int
    spans: bool
    matched: str


GRAM = 4  # word run used to find where in a paragraph a quote probably sits
MIN_GRAM_SHARE = 0.3  # a paragraph must share this much of the quote's word runs to be scored
SLACK = 3  # extra words kept each side of the best alignment


def _locate(words: list[str], seg_words: list[str]) -> tuple[int, float] | None:
    """Where `seg_words` most likely starts in `words`, and the share of its word runs found.

    One pass over the paragraph. Each shared 4-word run votes for a start position (its
    offset in the paragraph minus its offset in the quote). The most-voted start wins, so a
    changed word in the middle of a quote does not stop the rest from voting.
    """
    wanted: dict[tuple[str, ...], list[int]] = {}
    for k in range(len(seg_words) - GRAM + 1):
        wanted.setdefault(tuple(seg_words[k : k + GRAM]), []).append(k)
    if not wanted:
        return None
    votes: dict[int, int] = {}
    found: set[tuple[str, ...]] = set()
    for i in range(len(words) - GRAM + 1):
        gram = tuple(words[i : i + GRAM])
        offsets = wanted.get(gram)
        if offsets:
            found.add(gram)
            for k in offsets:
                votes[i - k] = votes.get(i - k, 0) + 1
    if not votes:
        return None
    start = max(votes, key=lambda d: (votes[d], -d))
    return start, len(found) / len(wanted)


def _score_window(
    words: list[str], seg: str, seg_len: int, boundary: int | None = None
) -> tuple[float, str] | None:
    """Best word-level agreement (0-100) between the quote and a stretch of `words`.

    With `boundary` (the index where a second paragraph starts), only stretches that cross it
    count, so a quote lying wholly in one paragraph is never credited to a join.
    """
    seg_words = seg.split()
    located = _locate(words, seg_words)
    if located is None or located[1] < MIN_GRAM_SHARE:
        return None
    start = located[0]
    best: tuple[float, str] | None = None
    for lo in range(max(0, start - SLACK), min(len(words), start + SLACK + 1)):
        for length in (seg_len - 1, seg_len, seg_len + 1):  # a word may be added or dropped
            window = words[lo : lo + length]
            if boundary is not None and not (lo < boundary < lo + len(window)):
                continue
            score = fuzz.ratio(seg_words, window)
            if best is None or score > best[0]:
                best = (score, " ".join(window))
    if best is None or best[0] < NEAR_THRESHOLD:
        return None
    return best


def _best_hit(paras: list[tuple[int, str]], segment: str) -> list[_Hit]:
    """All paragraphs (and joins of neighbours) where the segment fits, best first."""
    hits = [
        _Hit(score=100.0, para_no=no, spans=False, matched=segment)
        for no, text in paras
        if segment in text
    ]
    seg_len = len(segment.split())
    if not hits:
        split = [(no, text.split()) for no, text in paras]
        for idx, (no, words) in enumerate(split):
            scored = _score_window(words, segment, seg_len)
            if scored:
                hits.append(_Hit(score=scored[0], para_no=no, spans=False, matched=scored[1]))
            if idx + 1 < len(split):  # a quote that starts in one paragraph and ends in the next
                tail = words[-seg_len:]
                joined = tail + split[idx + 1][1][:seg_len]
                text = " ".join(joined)
                if segment in text and segment not in " ".join(tail) and segment not in " ".join(
                    joined[len(tail) :]
                ):
                    hits.append(_Hit(score=100.0, para_no=no, spans=True, matched=segment))
                    continue
                scored = _score_window(joined, segment, seg_len, boundary=len(tail))
                if scored:
                    hits.append(_Hit(score=scored[0], para_no=no, spans=True, matched=scored[1]))
    hits.sort(key=lambda h: (-h.score, h.para_no))
    return hits


_SENTENCE_BREAK = re.compile(r"(?<=[.?!;:])[\"\u201d')\]]*\s+(?=[A-Z\"\u201c(])")
MIN_PART_WORDS = 5


def _omission_check(paras: list[tuple[int, str]], quote: str) -> QuoteResult | None:
    """A quote whose sentences each appear in the SAME paragraph, in order, but with text left
    out in between and no '...' to say so. Real drafts do this; it is not an invented quote."""
    parts = [normalise(p) for p in _SENTENCE_BREAK.split(quote)]
    parts = [p for p in parts if p]
    if len(parts) < 2 or any(len(p.split()) < MIN_PART_WORDS for p in parts):
        return None
    tops = []
    for part in parts:
        hits = _best_hit(paras, part)
        if not hits:
            return None
        tops.append(hits[0])
    if len({h.para_no for h in tops}) != 1 or any(h.spans for h in tops):
        return None
    return QuoteResult(
        status="near_match", similarity=min(h.score for h in tops) / 100,
        para_nos=[tops[0].para_no], matched_text=tops[0].matched,
        changes=["each sentence is in the judgment, but text between them is left out"],
        flags=["omission"],
    )


def check_quote_in_paragraphs(paragraphs: list[tuple[int, str]], quote: str) -> QuoteResult:
    """paragraphs: (para_no, text) in order. Pure function, no database."""
    result = _check_segments(paragraphs, quote)
    if result.status != "not_found":
        return result
    # Not found as written. Try each '...'-separated piece; a piece that is several sentences of
    # one paragraph with text left out between them is rescued as an omission (near match).
    paras = [(no, normalise(text)) for no, text in paragraphs]
    pieces = [p for p in _ELLIPSIS.split(quote) if len(normalise(p).split()) >= MIN_SEGMENT_WORDS]
    found: list[QuoteResult] = []
    for piece in pieces:
        r = _check_segments(paragraphs, piece)
        if r.status == "not_found":
            r = _omission_check(paras, piece) or r
        if r.status == "not_found":
            return result
        found.append(r)
    if not any("omission" in r.flags for r in found):
        return result
    return QuoteResult(
        status="near_match", similarity=min(r.similarity for r in found),
        para_nos=found[0].para_nos, matched_text=found[0].matched_text,
        changes=[c for r in found for c in r.changes],
        flags=sorted({f for r in found for f in r.flags}),
    )


def _check_segments(paragraphs: list[tuple[int, str]], quote: str) -> QuoteResult:
    segments = split_segments(quote)
    if not segments:
        return QuoteResult(status="too_short", similarity=0.0)
    paras = [(no, normalise(text)) for no, text in paragraphs]

    worst = 100.0
    first_hits: list[_Hit] = []
    all_changes: list[str] = []
    all_flags: set[str] = set()
    all_noise = True
    spans = False
    for k, seg in enumerate(segments):
        hits = _best_hit(paras, seg)
        if not hits:
            return QuoteResult(status="not_found", similarity=0.0)
        top = hits[0]
        worst = min(worst, top.score)
        spans = spans or top.spans
        if k == 0:
            first_hits = hits
        if top.score < 100.0:
            changes, flags, noise = _describe_changes(seg, top.matched)
            all_changes += changes
            all_flags.update(flags)
            all_noise = all_noise and noise

    status: Literal["verbatim", "near_match"] = "verbatim" if worst >= 100.0 else "near_match"
    nos: list[int] = []
    for h in first_hits:
        if h.para_no not in nos:
            nos.append(h.para_no)
    return QuoteResult(
        status=status, similarity=worst / 100, para_nos=nos[:MAX_PARA_HITS],
        spans_paragraphs=spans, matched_text=first_hits[0].matched,
        changes=all_changes, flags=sorted(all_flags),
        noise_like=status == "near_match" and all_noise and bool(all_changes),
    )


def load_paragraphs(con: sqlite3.Connection, case_id: str) -> list[tuple[int, str]]:
    return con.execute(
        "SELECT para_no, text FROM paragraphs WHERE case_id = ? ORDER BY para_no", (case_id,)
    ).fetchall()


def check_quote(con: sqlite3.Connection, case_id: str, quote: str) -> QuoteResult:
    return check_quote_in_paragraphs(load_paragraphs(con, case_id), quote)
