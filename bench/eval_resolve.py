"""Evaluate the resolver on one split of the resolver benchmark (M3).

Each item hides the exact SCR/neutral number and gives the resolver only the SCC/AIR citation
and the case name. Reports, per cited format: how many resolved correctly, wrongly, or not at
all; and, for items whose cited case is not in the corpus, how often it wrongly returned one.

Tune on dev only. `--split test` is run once, at the end, with the threshold already fixed.

Usage: uv run python bench/eval_resolve.py [--split dev|test] [--threshold 0.85] [--errors N]
"""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from pramaan.citations.extract import Citation
from pramaan.citations.normalise import parse_citation
from pramaan.resolve.resolver import DEFAULT_THRESHOLD, resolve


def load(split: str) -> list[dict]:
    path = Path(f"bench/data/resolve_{split}.jsonl")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run(
    con: sqlite3.Connection, items: list[dict], threshold: float, leave_one_out: bool = False
) -> list[tuple[dict, object]]:
    """With leave_one_out, each item's true case is hidden, so 'no match' is the right answer."""
    results = []
    for item in items:
        if item["gold_kind"] == "anchor_not_found":
            continue  # gold unreliable, see bench/build_resolve.py
        fmt = item["cited_format"]
        cit = Citation(
            raw=item["cited_raw"], span=(0, 0), format=fmt, proposition="",
            parsed=parse_citation(item["cited_raw"], fmt), case_name=item["draft_name"],
        )
        if leave_one_out:
            if item["gold_kind"] != "in_corpus":
                continue
            res = resolve(con, cit, threshold, exclude_case=item["gold_case_id"])
            item = {**item, "gold_kind": "not_in_corpus", "gold_case_id": None}
        else:
            res = resolve(con, cit, threshold)
        results.append((item, res))
    return results


def outcome(item: dict, res) -> str:
    if item["gold_kind"] == "not_in_corpus":
        return "correct_none" if res.case_id is None else "false_match"
    if res.case_id == item["gold_case_id"]:
        return "correct"
    if res.case_id is None:
        return "ambiguous" if res.method == "ambiguous" else "missed"
    return "wrong_case"


def report(results: list[tuple[dict, object]], threshold: float) -> None:
    print(f"threshold {threshold}   items {len(results)}")
    by_fmt: dict[str, Counter] = {}
    for item, res in results:
        by_fmt.setdefault(item["cited_format"], Counter())[outcome(item, res)] += 1
    cols = ["correct", "wrong_case", "missed", "ambiguous", "correct_none", "false_match"]
    print(f"{'format':<12}{'n':>6}" + "".join(f"{c:>14}" for c in cols))
    for fmt, c in sorted(by_fmt.items()):
        print(f"{fmt:<12}{sum(c.values()):>6}" + "".join(f"{c[k]:>14}" for k in cols))
    pos = [(i, r) for i, r in results if i["gold_kind"] == "in_corpus"]
    ok = sum(1 for i, r in pos if outcome(i, r) == "correct")
    wrong = sum(1 for i, r in pos if outcome(i, r) == "wrong_case")
    if pos:
        print(f"\nin-corpus items: {len(pos)}  correct {ok} ({100 * ok / len(pos):.1f}%)  "
              f"wrong case {wrong} ({100 * wrong / len(pos):.1f}%)")
    neg = [(i, r) for i, r in results if i["gold_kind"] == "not_in_corpus"]
    fm = sum(1 for i, r in neg if outcome(i, r) == "false_match")
    if neg:
        print(f"not-in-corpus items: {len(neg)}  wrongly matched {fm} ({100 * fm / len(neg):.1f}%)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--leave-one-out", action="store_true",
                    help="hide each true case; correct answer is then no match")
    ap.add_argument("--errors", type=int, default=0, help="print this many failing items")
    args = ap.parse_args()
    con = sqlite3.connect("pramaan.db")
    items = load(args.split)
    skipped = sum(1 for i in items if i["gold_kind"] == "anchor_not_found")
    results = run(con, items, args.threshold, args.leave_one_out)
    report(results, args.threshold)
    print(f"({skipped} items with an unmatched anchor number are not scored)")
    shown = 0
    for item, res in results:
        if shown >= args.errors:
            break
        if outcome(item, res) in ("correct", "correct_none"):
            continue
        shown += 1
        print(f"\n[{outcome(item, res)}] {item['draft_name']!r}  {item['cited_raw']}  "
              f"gold={item['gold_case_id']}")
        print(f"   got={res.case_id} method={res.method} conf={res.confidence:.2f}")
        for a in res.alternatives:
            print(f"     {a.score:.2f} {a.case_id} {a.year} {a.title[:70]}")


if __name__ == "__main__":
    main()
