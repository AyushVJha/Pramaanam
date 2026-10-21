"""Hand-marking CLI for M2's extraction gold data (PROMPTS.md M2).

Per CLAUDE.md: gold labels are never produced by the AI. This tool only shows you what
citations/extract.py found (and some candidate misses) and records YOUR judgment —
it never decides correctness itself.

For each of 10 fixed real judgments (picked for a moderate, representative number of
candidate citations — see SELECTED_CNRS below), this:
  1. shows every citation candidate extract() found, in context, and asks you to mark it
     correct/incorrect (this measures PRECISION per format);
  2. separately scans for bare mentions of "SCC"/"AIR"/"INSC"/"SCR" that extract() did NOT
     already cover, and asks whether a real citation was missed there (this is a PARTIAL
     recall check for structured formats only — it cannot catch a case-name-only miss that
     doesn't contain one of those tokens, which is reported as "not measured" by
     eval_extraction.py, not guessed at).

Progress is saved after every single answer, so you can quit ('q') anytime and resume later
by re-running this script — already-answered items are skipped.

Run: uv run python scripts/label_extraction.py
"""

import json
import re
import sqlite3
from pathlib import Path

from pramaan.citations.extract import Citation, extract

DB_PATH = Path("pramaan.db")
GOLD_PATH = Path("bench/data/extraction_gold.jsonl")

# 10 real 2023 judgments with a moderate (9-16), representative number of candidate
# citations each — chosen over the DB's highest-count judgments (hundreds of citations,
# large constitutional benches) so the sample isn't dominated by a couple of outliers.
SELECTED_CNRS = [
    "ESCR010003762023", "ESCR010003452023", "ESCR010004772023", "ESCR010008012023",
    "ESCR010005032023", "ESCR010003822023", "ESCR010001992023", "ESCR010006782023",
    "ESCR010005132023", "ESCR010004582023",
]

_MISS_TOKEN = re.compile(r"\bSCC\b|\bAIR\b|\bINSC\b|\bSCR\b", re.IGNORECASE)
_CONTEXT = 150


def _judgment_text(con: sqlite3.Connection, cnr: str) -> str:
    rows = con.execute(
        "SELECT text FROM paragraphs WHERE case_id=? ORDER BY rowid", (cnr,)
    ).fetchall()
    return " ".join(r[0] for r in rows)


def _find_uncovered_miss_regions(text: str, citations: list[Citation]) -> list[tuple[int, int]]:
    covered = [c.span for c in citations]

    def is_covered(pos: int) -> bool:
        return any(start - 5 <= pos <= end + 5 for start, end in covered)

    regions = []
    for m in _MISS_TOKEN.finditer(text):
        if not is_covered(m.start()):
            regions.append((m.start(), m.end()))
    # merge regions within 40 chars of each other (same likely citation mention)
    merged: list[tuple[int, int]] = []
    for start, end in regions:
        if merged and start - merged[-1][1] <= 40:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _context(text: str, start: int, end: int) -> str:
    lo = max(0, start - _CONTEXT)
    hi = min(len(text), end + _CONTEXT)
    return f"...{text[lo:start]}>>>{text[start:end]}<<<{text[end:hi]}..."


def _load_answered(gold_path: Path) -> set[tuple[str, str, int]]:
    if not gold_path.exists():
        return set()
    answered = set()
    for line in gold_path.read_text().splitlines():
        row = json.loads(line)
        answered.add((row["cnr"], row["raw"], row["span"][0] if row["span"] else -1))
    return answered


def _append(gold_path: Path, row: dict) -> None:
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    with gold_path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def _prompt(question: str) -> str:
    return input(question).strip().lower()


_INTRO = """\
You're checking whether the PATTERN-MATCHING CODE correctly spotted a citation in the text
below — NOT whether the cited case is a real court case. Everything you need is on screen:
the judgment's own text, with the candidate marked >>>like this<<<. No searching needed.

  - "Correct": is that really a citation sitting right there, with the right span/format?
    (A judgment's own title header getting mistaken for a citation to someone else's case,
    or a case name getting chopped wrong, are both real failure modes to watch for.)
  - "Possible missed citation": is there an actual citation-shaped string near the
    highlighted word that the tool failed to flag at all?

Both are just reading comprehension against the text shown — never fact-checking.
"""


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    answered = _load_answered(GOLD_PATH)
    total_marked = len(answered)
    print(_INTRO)
    print(f"Resuming with {total_marked} items already marked (if any).\n")

    for cnr in SELECTED_CNRS:
        title = con.execute("SELECT title FROM cases WHERE cnr=?", (cnr,)).fetchone()[0]
        text = _judgment_text(con, cnr)
        citations = extract(text)

        print(f"\n===== {cnr}  {title[:70]} ({len(citations)} candidates) =====")

        for c in citations:
            if (cnr, c.raw, c.span[0]) in answered:
                continue
            print(f"\n[{c.format}] {c.raw!r}  case_name={c.case_name!r}  para_ref={c.para_ref}")
            print(_context(text, c.span[0], c.span[1]))
            ans = _prompt(
                "Did the tool get this right (right span/format)? [y]es/[n]o/[s]kip/[q]uit: "
            )
            if ans == "q":
                print(f"\nStopped. Total marked so far: {total_marked}")
                return
            if ans == "s":
                continue
            note = ""
            if ans == "n":
                note = input("  Why wrong (optional note): ").strip()
            _append(
                GOLD_PATH,
                {
                    "cnr": cnr, "raw": c.raw, "format": c.format, "span": list(c.span),
                    "source": "candidate", "label": "correct" if ans == "y" else "incorrect",
                    "note": note,
                },
            )
            total_marked += 1

        for start, end in _find_uncovered_miss_regions(text, citations):
            if (cnr, f"MISS@{start}", start) in answered:
                continue
            print("\n--- possible missed citation ---")
            print(_context(text, start, end))
            ans = _prompt(
                "Is there a citation-shaped string here the tool missed? [y]es/[n]o/[q]uit: "
            )
            if ans == "q":
                print(f"\nStopped. Total marked so far: {total_marked}")
                return
            if ans != "y":
                _append(
                    GOLD_PATH,
                    {
                        "cnr": cnr, "raw": f"MISS@{start}", "format": None, "span": [start, end],
                        "source": "miss_scan", "label": "not_missed", "note": "",
                    },
                )
                continue
            raw = input("  Type the exact citation text as it appears: ").strip()
            fmt = input("  Format (SCR/SCC/SCC_ONLINE/AIR/NEUTRAL/CASE_NAME): ").strip().upper()
            _append(
                GOLD_PATH,
                {
                    "cnr": cnr, "raw": raw or f"MISS@{start}", "format": fmt or None,
                    "span": [start, end], "source": "miss_scan", "label": "missed_citation",
                    "note": "",
                },
            )
            total_marked += 1

    print(f"\nAll 10 judgments done. Total marked: {total_marked}")
    print(f"Saved to {GOLD_PATH}")


if __name__ == "__main__":
    main()
