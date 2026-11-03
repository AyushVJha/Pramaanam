"""Sweep the near-match threshold on the DEV split only (M4). Never point this at test.

Runs the checker once at a low threshold, then derives each stricter threshold from the
similarity scores, so the sweep costs one pass.

Usage: uv run python bench/tune_quotes.py
"""

import sqlite3
from collections import Counter

from eval_quotes import ALTERED, load, run, status_at

from pramaan.checks import quotes

THRESHOLDS = [50, 60, 70, 75, 80, 85, 90, 95]


def main() -> None:
    quotes.NEAR_THRESHOLD = min(THRESHOLDS)
    con = sqlite3.connect("pramaan.db")
    results = run(con, load("dev"))
    print(f"dev items: {len(results)}\n")
    print(f"{'thr':>5}{'one_word':>10}{'negation':>10}{'number':>8}{'splice':>8}{'invented':>10}"
          f"{'false verbatim':>16}")
    for t in THRESHOLDS:
        right: Counter = Counter()
        total: Counter = Counter()
        fv = 0
        for item, res in results:
            got = status_at(res, t)
            total[item["kind"]] += 1
            right[item["kind"]] += got == item["expected_status"]
            fv += item["kind"] in ALTERED and got == "verbatim"
        pct = {k: 100 * right[k] / total[k] for k in total}
        print(f"{t:>5}{pct['one_word']:>9.1f}%{pct['negation']:>9.1f}%{pct['number']:>7.1f}%"
              f"{pct['splice']:>7.1f}%{pct['invented']:>9.1f}%{fv:>16}")


if __name__ == "__main__":
    main()
