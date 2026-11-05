"""Build the `treatments` table: which later judgment says what about an earlier case. (G1)

The Supreme Court's own headnotes list the cases a judgment dealt with, each followed by a label:

    "ADM Jabalpur v. Shivakant Shukla (1976) 2 SCC 521 : [1976] Suppl. SCR 172 - overruled."

We read those lines, resolve the cited case with the same proven-only rules as the verifier (an
exact number, or an SCC/AIR pair printed in two other judgments), and store one row per (cited,
citing, label). Nothing is guessed from prose: only the headnote pattern "<citation> - <label>"
counts.

Strong labels (overruled, partly overruled, disapproved, held per incuriam) can move a result to
NEEDS_REVIEW. Soft labels (distinguished, not followed, doubted, ...) are stored but only shown.
Limits, stated plainly: judgments without such a headnote add nothing; a label after a group of
citations is applied to every proven case in the group; treatments found only in running text are
not read. Precision is measured by scripts/check_treatments.py, not assumed.

Usage: uv run python -m pramaan.data.build_treatments [path/to/pramaan.db]
"""

import logging
import re
import sqlite3
import sys

from pramaan.checks.treatment import SOFT, STRONG  # noqa: F401 (documented here)
from pramaan.citations.extract import extract
from pramaan.data.build_aliases import citation_groups
from pramaan.pipeline import is_proven
from pramaan.resolve.resolver import resolve

logger = logging.getLogger(__name__)

LABEL = re.compile(
    r"\s[-–—]\s*(partly overruled|overruled|disapproved|held per incuriam|per incuriam"
    r"|not followed|distinguished|doubted|explained|followed|approved|affirmed|reversed)\b",
    re.IGNORECASE,
)
# Labels that carry no treatment. They still END a group of citations, so that a case marked
# "referred to" can never inherit the "overruled" written after the next citation.
NEUTRAL = re.compile(
    r"\s(?:[-\u2013\u2014]\s*)?(?:referred to|relied on|relied upon|considered|applied|cited"
    r"|upheld|reiterated|discussed|noted)\b",
    re.IGNORECASE,
)
MAX_GROUPS_PER_LABEL = 3  # "A and B - overruled" is fine; ten citations before a label is not
SNIPPET_BEFORE = 160

TREATMENTS_SCHEMA = """
DROP TABLE IF EXISTS treatments;
CREATE TABLE treatments (
    cited_case TEXT NOT NULL REFERENCES cases(cnr),
    citing_case TEXT NOT NULL REFERENCES cases(cnr),
    label TEXT NOT NULL,
    snippet TEXT NOT NULL      -- the headnote line, so a person can read the source
);
CREATE INDEX idx_treatments_cited ON treatments(cited_case);
"""


def _normal_label(label: str) -> str:
    label = label.lower()
    return "held per incuriam" if label == "per incuriam" else label


def treatments_in_text(
    con: sqlite3.Connection, citing_case: str, text: str
) -> list[tuple[str, str, str, str]]:
    """Rows (cited_case, citing_case, label, snippet) found in one paragraph."""
    if not LABEL.search(text):
        return []
    marks = sorted(list(LABEL.finditer(text)) + list(NEUTRAL.finditer(text)),
                   key=lambda m: m.start())
    groups = citation_groups(text, extract(text))
    rows: list[tuple[str, str, str, str]] = []
    previous_end = 0
    for m in marks:
        mine = [g for g in groups if g[-1].span[1] <= m.start() and g[0].span[0] >= previous_end]
        previous_end = m.end()
        if m.re is not LABEL:
            continue  # a neutral label: it only closes the group before it
        for group in mine[-MAX_GROUPS_PER_LABEL:]:
            cited = _resolve_group(con, group)
            if cited is None or cited == citing_case:
                continue
            start = max(0, group[0].span[0] - SNIPPET_BEFORE)
            snippet = " ".join(text[start : m.end()].split())
            rows.append((cited, citing_case, _normal_label(m.group(1)), snippet))
    return rows


def _resolve_group(con: sqlite3.Connection, group) -> str | None:
    """The case a chain like 'SCC : SCR' names, only when the proof rule is met and unanimous."""
    found = set()
    for c in group:
        if c.parsed is None:
            continue
        res = resolve(con, c)
        if res.case_id and is_proven(res):
            found.add(res.case_id)
    return found.pop() if len(found) == 1 else None


def build_treatments(con: sqlite3.Connection) -> int:
    con.executescript(TREATMENTS_SCHEMA)
    years = dict(con.execute("SELECT cnr, year FROM cases"))
    n_rows, seen = 0, set()
    for i, (cnr,) in enumerate(con.execute("SELECT cnr FROM cases ORDER BY cnr").fetchall()):
        for (text,) in con.execute("SELECT text FROM paragraphs WHERE case_id = ?", (cnr,)):
            if " - " not in text and "–" not in text and "—" not in text:
                continue
            for row in treatments_in_text(con, cnr, text):
                cited = row[0]
                if (years.get(cnr) or 0) < (years.get(cited) or 0):
                    continue  # a judgment cannot treat a case decided after it
                key = (row[0], row[1], row[2])
                if key in seen:
                    continue
                seen.add(key)
                con.execute("INSERT INTO treatments VALUES (?, ?, ?, ?)", row)
                n_rows += 1
        if i % 5000 == 0:
            logger.info("treatments: %d cases scanned, %d rows", i, n_rows)
    con.commit()
    return n_rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    connection = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "pramaan.db")
    logger.info("stored %d treatment rows", build_treatments(connection))
