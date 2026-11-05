"""Build support benchmark v2, DEV ONLY: v1 plus HARD negatives (right case, wrong proposition).

The failure that matters to a lawyer is "the case exists but does not say that". So the new
negative pairs a REAL case B with a proposition that was written about a DIFFERENT case, chosen
because its words overlap B's text as much as possible. Truth is by construction, not by a
model or a person: the proposition was cited to another case in another judgment, at least
MIN_YEAR_GAP years apart from B. It is noisy in the other direction (a case can happen to say
the same thing), so read "supported" on these as a warning sign, not proof of an error.

  positive      the sentence that cited B, paired with B (noisy, as in v1)
  easy_negative the sentence paired with an unrelated case (as in v1)
  hard_negative a sentence cited to another case, paired with B, picked for maximum word overlap

Only the dev split of the resolver benchmark is read. Test is built later, once, after freezing.
Usage: uv run python bench/build_support_v2.py [--n 20]
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

from build_support_dev import MAX_PER_CASE, MIN_YEAR_GAP, SRC, _h, looks_like_a_proposition

from pramaan.checks.quotes import load_paragraphs
from pramaan.checks.support import _tokens, rank_paragraphs

OUT = Path("bench/data/support_v2_dev.jsonl")
MIN_CONTEXT_CHARS = 200
MIN_OVERLAP = 0.35  # share of the proposition's topic words that the case text must contain
MAX_PROPOSITION_CHARS = 700
MAX_CITE_MARKS = 3  # the sentence itself cites the case: SCC + SCR + AIR is normal
_CITE = re.compile(r"\bSCC\b|\bSCR\b|\bAIR\b|\bINSC\b")
_LABEL = re.compile(
    r"\b(referred to|relied on|relied upon|overruled|followed|distinguished)\b", re.I
)


def is_clean(text: str) -> bool:
    """A proposition, not a headnote list: short, few reporter marks, no treatment labels."""
    return (len(text) <= MAX_PROPOSITION_CHARS and len(_CITE.findall(text)) <= MAX_CITE_MARKS
            and not _LABEL.search(text))


def overlap(proposition: str, case_vocab: set[str]) -> float:
    words = set(_tokens(proposition))
    return len(words & case_vocab) / len(words) if words else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20)
    n = parser.parse_args().n
    con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
    rows = [json.loads(line) for line in SRC.read_text().splitlines()]
    assert all(r["split"] == "dev" for r in rows), "this script must only read the dev split"
    rows = [r for r in rows if r["gold_kind"] == "in_corpus"
            and len(r["context"]) >= MIN_CONTEXT_CHARS and looks_like_a_proposition(r["context"])
            and is_clean(r["context"])]
    per_case: dict[str, int] = {}
    picked = []
    for r in sorted(rows, key=lambda r: _h(r["item_id"])):
        if per_case.get(r["gold_case_id"], 0) < MAX_PER_CASE:
            per_case[r["gold_case_id"]] = per_case.get(r["gold_case_id"], 0) + 1
            picked.append(r)
    picked = picked[:n]
    pool = picked  # sentences for hard negatives come from the same picked set

    marks = ",".join("?" * len(pool))
    years = dict(con.execute(
        f"SELECT cnr, CAST(substr(decision_date, -4) AS INT) FROM cases WHERE cnr IN ({marks})",
        [r["gold_case_id"] for r in pool],
    ))
    items, used = [], set()
    for i, r in enumerate(picked):
        case_b, paras_b = r["gold_case_id"], load_paragraphs(con, r["gold_case_id"])
        # positive
        items.append(_item(r, "positive", case_b, r["context"], paras_b))
        # easy negative: a case from another era (as v1)
        other = picked[(i + n // 2) % len(picked)]
        if abs(years[other["gold_case_id"]] - years[case_b]) >= MIN_YEAR_GAP:
            items.append(_item(r, "easy_negative", other["gold_case_id"], r["context"],
                               load_paragraphs(con, other["gold_case_id"])))
        # hard negative: an unused sentence cited to another case, with the most word overlap
        vocab = {w for _, t in paras_b for w in _tokens(t)}
        best = None
        for s in pool:
            if s["item_id"] in used or s["gold_case_id"] == case_b:
                continue
            if s["citing_case"] == r["citing_case"]:
                continue
            if abs(years[s["gold_case_id"]] - years[case_b]) < MIN_YEAR_GAP:
                continue
            score = overlap(s["context"], vocab)
            if score >= MIN_OVERLAP and (best is None or score > best[0]):
                best = (score, s)
        if best:
            _, s = best
            used.add(s["item_id"])
            item = _item(r, "hard_negative", case_b, s["context"], paras_b)
            item["item_id"] = f"{r['item_id']}-hard-{s['item_id']}"
            items.append(item)
    OUT.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n")
    from collections import Counter

    print(f"wrote {len(items)} items to {OUT}:", dict(Counter(i["kind"] for i in items)))


def _item(r, kind, case_id, proposition, paras) -> dict:
    return {
        "item_id": f"{r['item_id']}-{kind[:4]}", "kind": kind, "case_id": case_id,
        "proposition": proposition,
        "paragraphs": rank_paragraphs(paras, proposition),
        "expected": ["supported", "partially_supported"] if kind == "positive"
        else ["not_supported", "cannot_determine"],
    }


if __name__ == "__main__":
    main()
