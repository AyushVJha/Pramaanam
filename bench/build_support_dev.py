"""Build a small DEV-ONLY test set for choosing the support-judge model (M5).

Truth is by construction, not hand- or AI-labelled:
- positive: a real sentence from one judgment that cites case B, paired with case B itself.
  Expected verdict: supported or partially_supported. NOISY: the sentence may be quoting B only
  to distinguish it, or be cut off, so a "not_supported" here is not necessarily the judge's fault.
- negative: the same sentence paired with a different, unrelated case C (another decade, other
  parties). Expected verdict: not_supported (or cannot_determine). Almost never wrong.

Each item carries the top-5 retrieved paragraphs, so the judge job needs no database.
Only the dev split of the resolver benchmark is read. The test split is never opened.

Usage: uv run python bench/build_support_dev.py [--n 20]
"""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from pramaan.checks.quotes import load_paragraphs
from pramaan.checks.support import rank_paragraphs

SRC = Path("bench/data/resolve_dev.jsonl")
OUT = Path("bench/data/support_dev.jsonl")
MIN_CONTEXT_CHARS = 200  # shorter snippets are cut mid-sentence and say nothing
MAX_DIGIT_SHARE = 0.10  # a reference list is mostly numbers; a proposition is mostly words
MAX_SEMICOLONS = 2
# The sentence mentions the case only to set it aside, so "supported" would be the wrong answer.
SETTING_ASIDE = (
    "distinguish", "overrul", "not applicable", "no longer", "per incuriam", "dissent",
)
MAX_PER_CASE = 2
MIN_YEAR_GAP = 10  # the negative case must come from a different era


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def looks_like_a_proposition(text: str) -> bool:
    digits = sum(c.isdigit() for c in text) / len(text)
    lowered = text.lower()
    return (
        digits <= MAX_DIGIT_SHARE
        and text.count(";") <= MAX_SEMICOLONS
        and not any(w in lowered for w in SETTING_ASIDE)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20, help="positives; same number of negatives")
    n = parser.parse_args().n

    con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
    rows = [json.loads(line) for line in SRC.read_text().splitlines()]
    rows = [
        r for r in rows
        if r["gold_kind"] == "in_corpus" and len(r["context"]) >= MIN_CONTEXT_CHARS
        and looks_like_a_proposition(r["context"])
    ]
    assert all(r["split"] == "dev" for r in rows), "this script must only read the dev split"
    # At most MAX_PER_CASE items per cited case, in a fixed hash order, so reruns are identical.
    per_case: dict[str, int] = {}
    picked = []
    for r in sorted(rows, key=lambda r: _h(r["item_id"])):
        if per_case.get(r["gold_case_id"], 0) < MAX_PER_CASE:
            per_case[r["gold_case_id"]] = per_case.get(r["gold_case_id"], 0) + 1
            picked.append(r)
    picked = picked[:n]

    marks = ",".join("?" * len(picked))
    years = dict(con.execute(
        f"SELECT cnr, substr(decision_date, -4) FROM cases WHERE cnr IN ({marks})",
        [r["gold_case_id"] for r in picked],
    ))
    items = []
    for i, r in enumerate(picked):
        other = picked[(i + n // 2) % len(picked)]  # a different cited case
        true_case = r["gold_case_id"]
        for kind, case_id in (("positive", true_case), ("negative", other["gold_case_id"])):
            gap = abs(int(years[case_id]) - int(years[true_case]))
            if kind == "negative" and gap < MIN_YEAR_GAP:
                continue  # too close in time to be safely unrelated
            paragraphs = rank_paragraphs(load_paragraphs(con, case_id), r["context"])
            items.append({
                "item_id": f"{r['item_id']}-{kind[:3]}", "kind": kind, "case_id": case_id,
                "proposition": r["context"],
                "paragraphs": paragraphs,
                "expected": ["supported", "partially_supported"] if kind == "positive"
                else ["not_supported", "cannot_determine"],
            })
    OUT.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n")
    pos = sum(i["kind"] == "positive" for i in items)
    print(f"wrote {len(items)} items ({pos} positive, {len(items) - pos} negative) to {OUT}")
    print(f"items with no retrieved paragraph: {sum(not i['paragraphs'] for i in items)}")


if __name__ == "__main__":
    main()
