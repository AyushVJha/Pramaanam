"""Measure how usable the extracted text is, by decade of decision. Read-only.

For each decade: cases, share with zero paragraphs, median paragraphs / characters per case, and
an 'unknown-word rate': the share of word-like tokens (4+ letters) that never appear in a
vocabulary built from clean 2020s judgments. Old spellings and proper names also count as
unknown, so read the RATE AS A TREND across decades, not as an exact OCR error rate.
Samples SAMPLE cases per decade (fixed order, so reruns agree).

Usage: uv run python scripts/measure_text_quality.py
"""

import re
import sqlite3
import statistics
from collections import Counter

SAMPLE = 120
WORD = re.compile(r"[A-Za-z]{4,}")
con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
YEAR = "CAST(substr(c.decision_date, -4) AS INTEGER)"


def case_text(cnr: str) -> str:
    rows = con.execute("SELECT text FROM paragraphs WHERE case_id = ? ORDER BY para_no", (cnr,))
    return " ".join(r[0][:20000] for r in rows)  # cap one huge last paragraph


# vocabulary from clean modern text
vocab: Counter = Counter()
for (cnr,) in con.execute(
    f"SELECT cnr FROM cases c WHERE {YEAR} BETWEEN 2020 AND 2025 ORDER BY cnr LIMIT 300"
).fetchall():
    vocab.update(w.lower() for w in WORD.findall(case_text(cnr)))
known = {w for w, n in vocab.items() if n >= 5}
print(f"vocabulary: {len(known)} words from 300 judgments of 2020-2025\n")

header = ["decade", "cases", "zero-para", "med paras", "med chars", "unknown-word rate"]
print("".join(f"{h:<9}" if i == 0 else f"{h:>18}" for i, h in enumerate(header)))
for decade in range(1950, 2030, 10):
    total, zero = con.execute(
        f"SELECT COUNT(*), SUM(NOT EXISTS (SELECT 1 FROM paragraphs p WHERE p.case_id = c.cnr)) "
        f"FROM cases c WHERE {YEAR} BETWEEN ? AND ?", (decade, decade + 9),
    ).fetchone()
    if not total:
        continue
    sample = [r[0] for r in con.execute(
        f"SELECT cnr FROM cases c WHERE {YEAR} BETWEEN ? AND ? AND EXISTS "
        "(SELECT 1 FROM paragraphs p WHERE p.case_id = c.cnr) ORDER BY cnr LIMIT 100000",
        (decade, decade + 9),
    )]
    step = max(len(sample) // SAMPLE, 1)
    sample = sample[::step][:SAMPLE]
    paras, chars, unk, tok = [], [], 0, 0
    for cnr in sample:
        text = case_text(cnr)
        words = [w.lower() for w in WORD.findall(text)]
        n_paras = con.execute("SELECT COUNT(*) FROM paragraphs WHERE case_id=?", (cnr,))
        paras.append(n_paras.fetchone()[0])
        chars.append(len(text))
        tok += len(words)
        unk += sum(w not in known for w in words)
    print(
        f"{decade}s{'':<4}{total:>18}{100 * (zero or 0) / total:>17.1f}%"
        f"{statistics.median(paras):>18.0f}{statistics.median(chars):>18.0f}"
        f"{100 * unk / max(tok, 1):>17.1f}%"
    )
