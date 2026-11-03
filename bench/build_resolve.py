"""Build the resolver benchmark from real citing sentences in the corpus (M3).

Ground truth is NOT hand-labelled and NOT written by an AI. It comes from the judgments
themselves: when a judgment writes a parallel citation such as

    Om Kumar v. Union of India, (2001) 2 SCC 386 : [2001] 1 SCR 1

the SCR (or neutral) number identifies the cited case by exact lookup. We then hide that number
and ask the resolver to find the same case from the SCC/AIR citation plus the case name, which
is the situation for a draft that only gives an SCC or AIR number.

Items whose SCR/neutral number is not found in the corpus are kept as "anchor_not_found" but are
NOT scored. Reading the test split showed that most of them are the same case under a mistyped or
OCR-garbled number (a dropped digit, a different volume), so "no match" is not a safe gold label.
False matches are measured instead by leave-one-out (bench/eval_resolve.py --leave-one-out).

Split: a fixed hash of the CITING case id, 30% dev and 70% test, so no judgment's citations are
in both halves. The split is frozen: do not rerun this script and overwrite the files without
approval. Thresholds are tuned on dev only.

Usage: uv run python bench/build_resolve.py
"""

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from pramaan.citations.extract import Citation, extract
from pramaan.resolve.resolver import lookup_exact

DB_PATH = Path("pramaan.db")
OUT_DIR = Path("bench/data")
DEV_PERCENT = 30
MAX_PER_GOLD_CASE = 3  # stops a few famous cases from dominating the accuracy figure
APPROX_FORMATS = {"SCC", "AIR", "SCC_ONLINE"}  # cannot be looked up by number in the corpus
EXACT_FORMATS = {"SCR", "NEUTRAL"}
# Parallel citations are written "A : B : C". A comma or semicolon could be a list of different
# cases, which would pair a number with the wrong case, so only whitespace and a colon count.
_NO_TEXT_BETWEEN = re.compile(r"^[\s:]*$")
MAX_YEAR_GAP = 2  # parallel citations of one case are within a couple of years of each other
_TOKENS = re.compile(r"\bSCC\b|\bAIR\b|\bINSC\b|\bSCR\b")


def split_of(citing_case: str) -> str:
    digest = hashlib.sha256(citing_case.encode()).hexdigest()
    return "dev" if int(digest, 16) % 100 < DEV_PERCENT else "test"


def _clusters(text: str, cits: list[Citation]) -> list[list[Citation]]:
    """Group structured citations that sit next to each other, e.g. 'SCC : AIR : SCR'."""
    structured = sorted((c for c in cits if c.format != "CASE_NAME"), key=lambda c: c.span)
    groups: list[list[Citation]] = []
    for c in structured:
        if groups and _NO_TEXT_BETWEEN.match(text[groups[-1][-1].span[1] : c.span[0]]):
            groups[-1].append(c)
        else:
            groups.append([c])
    return groups


_NAME_TO_CITATION = re.compile(r"^[\s,(\[]*$")


def name_directly_before(text: str, name: str, cluster_start: int) -> bool:
    """True if `name` ends right before the citations, with only a comma or bracket between.

    In footnote lists ("1 [2021] 1 SCR 344 : (2021) 4 SCC 309 2 ...") the case name sits far
    away in the body text, so the name and the numbers must not be paired.
    """
    pattern = r"\s+".join(re.escape(w) for w in name.split())
    ends = [m.end() for m in re.finditer(pattern, text[:cluster_start])]
    return bool(ends) and bool(_NAME_TO_CITATION.match(text[ends[-1] : cluster_start]))


def items_from_paragraph(con: sqlite3.Connection, citing_case: str, text: str) -> list[dict]:
    out = []
    cits = extract(text)
    for group in _clusters(text, cits):
        name = next((c.case_name for c in group if c.case_name), None)
        anchors = [c for c in group if c.format in EXACT_FORMATS and c.parsed]
        tested = [c for c in group if c.format in APPROX_FORMATS and c.parsed]
        if not name or not anchors or not tested:
            continue
        if not name_directly_before(text, name, group[0].span[0]):
            continue
        anchor = anchors[0]
        hits = lookup_exact(con, anchor.parsed)
        if len(hits) > 1:
            continue  # the anchor itself is ambiguous, so it cannot give a clean answer
        gold = hits[0].case_id if hits else None
        if gold == citing_case:
            continue  # a judgment citing itself
        for c in tested:
            if abs(c.parsed.year - anchor.parsed.year) > MAX_YEAR_GAP:
                continue  # the two numbers are probably for different cases
            out.append(
                {
                    "citing_case": citing_case,
                    "draft_name": name,
                    "cited_raw": c.raw,
                    "cited_format": c.format,
                    "cited_year": c.parsed.year,
                    "context": c.proposition[:300],
                    "gold_kind": "in_corpus" if gold else "anchor_not_found",
                    "gold_case_id": gold,
                    "gold_anchor": anchor.raw,
                }
            )
    return out


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    seen: set[tuple] = set()
    per_gold: dict[tuple, int] = {}
    rows: list[dict] = []
    query = "SELECT case_id, text FROM paragraphs ORDER BY case_id, para_no"
    for citing_case, text in con.execute(query):
        if not _TOKENS.search(text):
            continue
        split = split_of(citing_case)
        for item in items_from_paragraph(con, citing_case, text):
            key = (item["citing_case"], item["draft_name"], item["cited_raw"])
            gold_key = (split, item["gold_case_id"] or item["gold_anchor"])
            if key in seen or per_gold.get(gold_key, 0) >= MAX_PER_GOLD_CASE:
                continue
            seen.add(key)
            per_gold[gold_key] = per_gold.get(gold_key, 0) + 1
            rows.append({**item, "split": split})

    for r in rows:
        r["item_id"] = hashlib.sha1(
            f"{r['citing_case']}|{r['draft_name']}|{r['cited_raw']}".encode()
        ).hexdigest()[:12]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for split in ("dev", "test"):
        part = [r for r in rows if r["split"] == split]
        path = OUT_DIR / f"resolve_{split}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part))
        kinds = Counter(r["gold_kind"] for r in part)
        print(f"{split}: {len(part)} items  {kinds}  -> {path}")


if __name__ == "__main__":
    main()
