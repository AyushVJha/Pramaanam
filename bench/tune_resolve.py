"""Sweep the fuzzy threshold on the DEV split only and print the trade-off (M3).

A wrong match is worse than a miss: a wrong match could mark a bad citation VERIFIED, while a
miss just becomes NOT_FOUND_IN_CORPUS. So the table shows both, and the threshold is chosen
as the lowest one whose wrong-case rate and lookalike false-match rate stay under a limit.

This script is hard-wired to dev. Never point it at test.

Usage: uv run python bench/tune_resolve.py
"""

import sqlite3
from collections import Counter

from eval_resolve import load, outcome, run

THRESHOLDS = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]


def main() -> None:
    con = sqlite3.connect("pramaan.db")
    items = load("dev")
    print(f"dev items: {len(items)}\n")
    print(f"{'thr':>5}{'correct%':>10}{'wrong%':>8}{'missed%':>9}{'ambig%':>8}"
          f"{'LOO false-match%':>19}")
    for t in THRESHOLDS:
        pos = [(i, r) for i, r in run(con, items, t) if i["gold_kind"] == "in_corpus"]
        c = Counter(outcome(i, r) for i, r in pos)
        n = len(pos)
        loo = run(con, items, t, leave_one_out=True)
        fm = sum(1 for i, r in loo if outcome(i, r) == "false_match")
        print(f"{t:>5.2f}{100 * c['correct'] / n:>10.1f}{100 * c['wrong_case'] / n:>8.1f}"
              f"{100 * c['missed'] / n:>9.1f}{100 * c['ambiguous'] / n:>8.1f}"
              f"{100 * fm / len(loo):>19.1f}")


if __name__ == "__main__":
    main()
