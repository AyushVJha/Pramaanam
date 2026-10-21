"""Precision/recall per citation format, computed ONLY from bench/data/extraction_gold.jsonl
— the hand-marked labels scripts/label_extraction.py produced. Never fabricates a number for
a format with no gold data; reports "not measured" instead (CLAUDE.md hard rule).

Precision (per format): of the candidates extract() actually found and you marked, what
fraction were correct.

Recall (per structured format — SCR/SCC/SCC_ONLINE/AIR/NEUTRAL only): correct candidates /
(correct candidates + citations you flagged as missed during the miss-scan). This is a
PARTIAL recall estimate — the miss-scan only looks for bare "SCC"/"AIR"/"INSC"/"SCR" tokens,
so it can't find every possible miss, and it can't find a missed CASE_NAME at all. Reported
as "not measured" for CASE_NAME, not guessed at.

Run: uv run python scripts/eval_extraction.py (after scripts/label_extraction.py)
"""

import json
from pathlib import Path

GOLD_PATH = Path("bench/data/extraction_gold.jsonl")
STRUCTURED_FORMATS = ["SCR", "SCC", "SCC_ONLINE", "AIR", "NEUTRAL"]


def load_gold(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    rows = load_gold(GOLD_PATH)
    if not rows:
        print(f"No gold data at {GOLD_PATH} yet — run scripts/label_extraction.py first.")
        return

    candidates = [r for r in rows if r["source"] == "candidate"]
    misses = [r for r in rows if r["source"] == "miss_scan" and r["label"] == "missed_citation"]

    formats = sorted({r["format"] for r in candidates if r["format"]} | set(STRUCTURED_FORMATS))

    print(f"{'format':<12} {'n_candidates':>12} {'precision':>10} {'recall':>10}")
    for fmt in formats:
        fmt_candidates = [r for r in candidates if r["format"] == fmt]
        n = len(fmt_candidates)
        if n == 0:
            print(f"{fmt:<12} {'0':>12} {'not measured':>10} {'not measured':>10}")
            continue
        n_correct = sum(1 for r in fmt_candidates if r["label"] == "correct")
        precision = n_correct / n

        if fmt in STRUCTURED_FORMATS:
            n_missed = sum(1 for r in misses if r["format"] == fmt)
            denom = n_correct + n_missed
            recall = f"{n_correct / denom:.2f}" if denom else "not measured"
        else:
            recall = "not measured"

        print(f"{fmt:<12} {n:>12} {precision:>10.2f} {recall:>10}")

    n_unformatted_misses = sum(1 for r in misses if not r["format"])
    if n_unformatted_misses:
        print(
            f"\n{n_unformatted_misses} missed citation(s) recorded without a format label "
            "(left blank during marking) — excluded from the per-format recall above."
        )

    print(f"\nTotal gold entries: {len(rows)}  (candidates: {len(candidates)}, "
          f"confirmed misses: {len(misses)})")


if __name__ == "__main__":
    main()
