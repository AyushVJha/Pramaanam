"""End-to-end check of the citation pipeline on the resolver benchmark (no LLM, dev or test). (M7)

Each item is a real citation printed in a real judgment, with the true case known (or known to be
outside the corpus). We run the whole pipeline with the AI support check off and count what status
comes out. The number that matters most is FALSE VERIFIED: VERIFIED on a case that is not the true
one. Everything else is a coverage question (how many get a proven VERIFIED vs NEEDS_REVIEW).

Only the existence/identity part is tested here (no quotes: the benchmark has none).
Usage: uv run python bench/eval_pipeline.py [--split dev|test]
"""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from pramaan.citations.extract import Citation
from pramaan.citations.normalise import parse_citation
from pramaan.pipeline import check_citation


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    args = ap.parse_args()
    items = [
        json.loads(line)
        for line in Path(f"bench/data/resolve_{args.split}.jsonl").read_text().splitlines()
        if line.strip()
    ]
    con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
    table: Counter = Counter()
    false_verified = []
    why: Counter = Counter()
    scored = 0
    for item in items:
        if item["gold_kind"] == "anchor_not_found":
            continue
        fmt = item["cited_format"]
        cit = Citation(
            raw=item["cited_raw"], span=(0, 0), format=fmt, proposition="",
            parsed=parse_citation(item["cited_raw"], fmt), case_name=item["draft_name"],
        )
        r = check_citation(con, cit, use_llm=False, exclude_citing=item["citing_case"])
        scored += 1
        right = (
            r.case_id == item["gold_case_id"] if item["gold_kind"] == "in_corpus"
            else r.case_id is None
        )
        table[(item["gold_kind"], r.status, "right case" if right else "WRONG case")] += 1
        if r.status == "NEEDS_REVIEW":
            if r.resolution.method == "alias":
                why[f"alias, {r.resolution.witnesses} witness(es)"] += 1
            else:
                why[f"method {r.resolution.method}"] += 1
        if r.status == "VERIFIED" and not right:
            false_verified.append((item["draft_name"], item["cited_raw"], r.case_title))
    print(f"split {args.split}: {scored} items, AI support check off\n")
    for (kind, status, right), n in sorted(table.items()):
        print(f"{kind:14} {status:20} {right:11} {n:5}")
    print("\nWhy NEEDS_REVIEW:", dict(why))
    verified = sum(n for (_, s, _), n in table.items() if s == "VERIFIED")
    print(f"\nVERIFIED: {verified}; FALSE VERIFIED: {len(false_verified)}")
    for row in false_verified[:10]:
        print("  ", row)


if __name__ == "__main__":
    main()
