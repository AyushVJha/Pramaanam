"""End-to-end pipeline on the quote benchmark: citation number + name + quote + paragraph. (M7)

Each item of bench/data/quotes_<split>.jsonl is a real quote (or a deliberately altered one) from a
known judgment. We write it as a draft citation using the judgment's own unique citation number and
title, run the whole pipeline (AI check off) and tabulate kind x status.

The safety number: altered or invented quotes that came out VERIFIED (must be 0).
Usage: uv run python bench/eval_pipeline_quotes.py [--split dev|test]
"""

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from pramaan.citations.extract import Citation
from pramaan.citations.normalise import ParsedCitation
from pramaan.pipeline import check_citation

ALTERED = {"one_word", "negation", "number", "splice", "invented"}


def own_citation(con: sqlite3.Connection, case_id: str) -> tuple[str, ParsedCitation] | None:
    """A citation number that belongs to this case alone (SCR first, then INSC)."""
    rows = con.execute(
        "SELECT reporter, year, volume, page, raw FROM case_citations WHERE case_id = ? "
        "ORDER BY CASE reporter WHEN 'SCR' THEN 0 ELSE 1 END",
        (case_id,),
    ).fetchall()
    for reporter, year, volume, page, raw in rows:
        n = con.execute(
            "SELECT COUNT(DISTINCT case_id) FROM case_citations WHERE reporter = ? AND year = ? "
            "AND volume IS ? AND page = ?",
            (reporter, year, volume, page),
        ).fetchone()[0]
        if n == 1:
            return raw, ParsedCitation(reporter=reporter, year=year, volume=volume, page=page)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    args = ap.parse_args()
    items = [
        json.loads(line)
        for line in Path(f"bench/data/quotes_{args.split}.jsonl").read_text().splitlines()
        if line.strip()
    ]
    con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
    table: dict[str, Counter] = defaultdict(Counter)
    bad = []
    skipped = 0
    for it in items:
        own = own_citation(con, it["case_id"])
        if own is None:
            skipped += 1
            continue
        raw, parsed = own
        title = con.execute(
            "SELECT title FROM cases WHERE cnr = ?", (it["case_id"],)
        ).fetchone()[0]
        name = title.replace(" versus ", " v. ")
        cit = Citation(
            raw=raw, span=(0, 0), format=parsed.reporter, parsed=parsed, case_name=name,
            proposition="", quoted_text=it["quote"], para_ref=it["cited_para"],
        )
        r = check_citation(con, cit, use_llm=False)
        table[it["kind"]][r.status] += 1
        if r.status == "NAME_MISMATCH":
            print("NAME_MISMATCH on own title:", name, "|", r.reason[:120])
        if it["kind"] in ALTERED and r.status == "VERIFIED":
            bad.append((it["kind"], it["quote"][:80]))
    print(f"split {args.split}: {len(items) - skipped} scored, {skipped} skipped\n")
    for kind in sorted(table):
        row = ", ".join(f"{s} {n}" for s, n in sorted(table[kind].items()))
        print(f"{kind:26} {row}")
    print(f"\nALTERED/INVENTED QUOTES VERIFIED: {len(bad)}")
    for b in bad[:10]:
        print("  ", b)


if __name__ == "__main__":
    main()
