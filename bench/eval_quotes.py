"""Evaluate the quote and paragraph checks on one split of the quote benchmark (M4).

Truth is by construction (see bench/build_quotes.py), so every status is known:
real quotes must be "verbatim"; one word, a negation or a number changed must be "near_match";
spliced and invented quotes must be "not_found". The error that matters most is an altered
quote reported "verbatim", because that would let a bad quote pass.

Usage: uv run python bench/eval_quotes.py [--split dev|test] [--threshold 80]
Tune the threshold on dev only (bench/tune_quotes.py). Run test once, with it fixed.
"""

import argparse
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

from pramaan.checks import quotes
from pramaan.checks.paragraph import check_paragraph

ALTERED = {"one_word", "negation", "number", "splice", "invented"}


def load(split: str) -> list[dict]:
    path = Path(f"bench/data/quotes_{split}.jsonl")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run(con: sqlite3.Connection, items: list[dict]) -> list[tuple[dict, quotes.QuoteResult]]:
    return [(i, quotes.check_quote(con, i["case_id"], i["quote"])) for i in items]


def status_at(result: quotes.QuoteResult, threshold: float) -> str:
    """The status this result would have at `threshold` (percent), from its similarity."""
    if result.status == "near_match" and result.similarity * 100 < threshold:
        return "not_found"
    return result.status


def report(results: list[tuple[dict, quotes.QuoteResult]], threshold: float) -> None:
    by_kind: dict[str, Counter] = defaultdict(Counter)
    flag_ok = Counter()
    flag_n = Counter()
    para = Counter()
    false_verbatim = 0
    n_altered = 0
    for item, res in results:
        got = status_at(res, threshold)
        by_kind[item["kind"]][got] += 1
        if item["kind"] in ALTERED:
            n_altered += 1
            false_verbatim += got == "verbatim"
        if item["expected_flag"]:
            flag_n[item["kind"]] += 1
            if got == "near_match" and item["expected_flag"] in res.flags:
                flag_ok[item["kind"]] += 1
        if item["cited_para"] is not None and got == "verbatim":
            pr = check_paragraph(item["cited_para"], res)
            para[(item["kind"], pr.status == item["expected_para_status"])] += 1

    print(f"threshold {threshold}   items {len(results)}\n")
    print(f"{'kind':<26}{'n':>5}{'right status':>14}   what it was called")
    for kind, c in sorted(by_kind.items()):
        expected = next(i["expected_status"] for i, _ in results if i["kind"] == kind)
        n = sum(c.values())
        print(f"{kind:<26}{n:>5}{100 * c[expected] / n:>13.1f}%   "
              + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    print(f"\naltered quotes reported verbatim: {false_verbatim} of {n_altered}")
    for kind in flag_n:
        print(f"{kind} flag raised: {flag_ok[kind]} of {flag_n[kind]}")
    for kind in sorted({k for k, _ in para}):
        ok, bad = para[(kind, True)], para[(kind, False)]
        print(f"paragraph check on {kind}: {ok} of {ok + bad} right")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--threshold", type=float, default=quotes.NEAR_THRESHOLD)
    args = ap.parse_args()
    quotes.NEAR_THRESHOLD = min(args.threshold, quotes.NEAR_THRESHOLD)  # never hide a hit early
    con = sqlite3.connect("pramaan.db")
    t = time.time()
    results = run(con, load(args.split))
    report(results, args.threshold)
    print(f"\n{len(results)} checks in {time.time() - t:.0f} s")


if __name__ == "__main__":
    main()
