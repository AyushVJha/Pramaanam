"""Build the quote-check benchmark from judgments in the corpus (M4).

Truth comes from construction, not from labelling:
- a "real" quote is a sentence lifted from a judgment, so it IS in that judgment;
- an altered quote is that sentence changed in a known way (one word swapped, a negation
  added or removed, a number changed, two distant paragraphs spliced), so it is NOT verbatim;
- an invented quote is a sentence from a different judgment, checked to be absent.

This is easier than real hallucinated quotes, because a "real" quote here is copied from the
same text the checker reads (no OCR or typing differences). bench/measure_real_quotes.py gives
the complementary, unlabelled measurement on quotes that real judgments take from other
judgments. M6 adds realistic hallucinations.

Cases are picked by a fixed hash of the case id (spread over all years). Split by a fixed hash:
30% dev, 70% test, so no judgment is in both. The split is frozen. Do not rerun and overwrite
without approval.

Usage: uv run python bench/build_quotes.py
"""

import hashlib
import json
import random
import re
import sqlite3
from pathlib import Path

DB_PATH = Path("pramaan.db")
OUT_DIR = Path("bench/data")
N_CASES = 400
DEV_PERCENT = 30
MIN_WORDS, MAX_WORDS = 15, 60
MIN_PARAS = 8
AUX = {"is", "was", "are", "were", "has", "have", "had", "can", "shall", "may", "will", "would",
       "should", "does", "did", "could", "must"}
_SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z])")


def h(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest(), 16)


def split_of(case_id: str) -> str:
    return "dev" if h(case_id) % 100 < DEV_PERCENT else "test"


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if MIN_WORDS <= len(s.split()) <= MAX_WORDS]


def swap_word(sent: str, rng: random.Random, pool: list[str]) -> str | None:
    words = sent.split()
    spots = [i for i, w in enumerate(words) if w.isalpha() and len(w) >= 5 and w.lower() not in AUX]
    if not spots or not pool:
        return None
    i = rng.choice(spots)
    new = rng.choice([w for w in pool if w.lower() != words[i].lower()] or pool)
    words[i] = new
    return " ".join(words)


def flip_negation(sent: str) -> str | None:
    words = sent.split()
    for i, w in enumerate(words):
        if w.lower().strip(",;") == "not":
            return " ".join(words[:i] + words[i + 1 :])  # remove a negation
    for i, w in enumerate(words):
        if w.lower() in AUX:
            return " ".join(words[: i + 1] + ["not"] + words[i + 1 :])  # add one
    return None


def change_number(sent: str) -> str | None:
    m = re.search(r"\b\d{2,4}\b", sent)
    if not m:
        return None
    digits = m.group(0)
    changed = str((int(digits) + 7) % (10 ** len(digits))).zfill(len(digits))
    return sent[: m.start()] + changed + sent[m.end() :]


def splice(a: str, b: str) -> str:
    wa, wb = a.split(), b.split()
    return " ".join(wa[: len(wa) // 2] + wb[len(wb) // 2 :])


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    cases = [
        r[0] for r in con.execute(
            "SELECT case_id FROM paragraphs GROUP BY case_id HAVING COUNT(*) >= ?", (MIN_PARAS,)
        )
    ]
    cases = sorted(cases, key=lambda c: h("pick" + c))[:N_CASES]
    rows: list[dict] = []
    for case_id in cases:
        paras = con.execute(
            "SELECT para_no, text FROM paragraphs WHERE case_id = ? ORDER BY para_no", (case_id,)
        ).fetchall()
        rng = random.Random(h("rng" + case_id))
        full = " ".join(t for _, t in paras).lower()
        sents = [(no, s) for no, t in paras if len(t) < 20000 for s in sentences(t)]
        if len(sents) < 6:
            continue
        no, base = sents[rng.randrange(len(sents))]
        pool = [w for _, s in sents for w in s.split() if w.isalpha() and len(w) >= 5]

        def add(kind, quote, expected, cited=None, expected_para=None, flag=None, source=no):
            if quote:
                rows.append({
                    "case_id": case_id, "kind": kind, "quote": quote, "source_para": source,
                    "expected_status": expected, "expected_flag": flag,
                    "cited_para": cited, "expected_para_status": expected_para,
                    "split": split_of(case_id),
                })

        add("real", base, "verbatim", cited=no, expected_para="correct")
        add("real_wrong_para_adjacent", base, "verbatim", cited=no + 1, expected_para="adjacent")
        far = no + 6 if no + 6 <= paras[-1][0] else max(1, no - 6)
        add("real_wrong_para_far", base, "verbatim", cited=far, expected_para="wrong_paragraph")
        add("one_word", swap_word(base, rng, pool), "near_match")
        add("negation", flip_negation(base), "near_match", flag="negation")
        add("number", change_number(base), "near_match", flag="number")
        others = [(n, s) for n, s in sents if abs(n - no) >= 3]
        if others:
            n2, s2 = others[rng.randrange(len(others))]
            add("splice", splice(base, s2), "not_found")
        # A sentence from some other judgment that is absent from this one.
        other_case = cases[(cases.index(case_id) + 1) % len(cases)]
        other = con.execute(
            "SELECT text FROM paragraphs WHERE case_id = ? ORDER BY para_no LIMIT 40", (other_case,)
        ).fetchall()
        cand = [s for (t,) in other if len(t) < 20000 for s in sentences(t)]
        cand = [s for s in cand if " ".join(re.findall(r"\w+", s.lower())) not in
                " ".join(re.findall(r"\w+", full))]
        if cand:
            add("invented", cand[rng.randrange(len(cand))], "not_found", source=None)

    for r in rows:
        r["item_id"] = hashlib.sha1(f"{r['case_id']}|{r['kind']}".encode()).hexdigest()[:12]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for split in ("dev", "test"):
        part = [r for r in rows if r["split"] == split]
        (OUT_DIR / f"quotes_{split}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part)
        )
        kinds: dict[str, int] = {}
        for r in part:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        print(f"{split}: {len(part)} items from {len({r['case_id'] for r in part})} cases  {kinds}")


if __name__ == "__main__":
    main()
