"""Read-only tools the agents may call. (A2)

Two small classes, each bound to one open database connection (and one judgment for the reader).
They do three jobs beyond fetching data:
- every tool returns a short text, because that text goes back into the model's prompt;
- each class remembers what it has SHOWN the model, so the caller can later check that an answer
  only points at things the agent actually saw ("evidence by pointer, and it must have been seen");
- nothing here writes: the database is opened read-only by the callers (tested).
"""

import re
import sqlite3

from pydantic import BaseModel, Field

from pramaan.agents.runtime import Tool
from pramaan.checks.quotes import load_paragraphs
from pramaan.checks.support import best_sentence, rank_paragraphs
from pramaan.resolve.names import DECISION_YEAR_SQL, find_name_candidates

SNIPPET_CHARS = 300
READ_CHARS = 2500


class SearchArgs(BaseModel):
    query: str = Field(description="legal terms to look for in this judgment")


class ReadArgs(BaseModel):
    para_no: int = Field(
        description="a paragraph number exactly as shown by an earlier search; it can be negative"
    )


class JudgmentReader:
    """Search and read the paragraphs of ONE judgment."""

    def __init__(self, con: sqlite3.Connection, case_id: str):
        self.paragraphs = load_paragraphs(con, case_id)
        self.text = dict(self.paragraphs)
        self.order = [n for n, _ in self.paragraphs]
        self.shown: set[int] = set()  # paragraph numbers the model has seen (even as a snippet)
        self.read: set[int] = set()  # paragraph numbers the model has read in full
        self.searches = 0

    def _snippet(self, para_no: int, query: str) -> str:
        return f"[para {para_no}] {best_sentence(self.text[para_no], query, SNIPPET_CHARS)}"

    def search(self, args: SearchArgs) -> str:
        self.searches += 1
        hits = rank_paragraphs(self.paragraphs, args.query, k=5)
        if not hits:
            return "No paragraph shares a topic word with that query. Try other words."
        self.shown.update(n for n, _ in hits)
        return "\n".join(self._snippet(n, args.query) for n, _ in hits)

    def read_paragraph(self, args: ReadArgs) -> str:
        if args.para_no not in self.text:
            hint = ""
            if -args.para_no in self.text:  # the model dropped a minus sign
                hint = (f" Paragraph numbers can be negative: did you mean {-args.para_no}? "
                        "Copy the number exactly as shown, minus sign included.")
            return f"There is no paragraph {args.para_no} in this judgment.{hint}"
        self.shown.add(args.para_no)
        self.read.add(args.para_no)
        i = self.order.index(args.para_no)
        before = self.order[i - 1] if i > 0 else None
        after = self.order[i + 1] if i + 1 < len(self.order) else None
        body = self.text[args.para_no][:READ_CHARS]
        return f"[para {args.para_no}] (previous: {before}, next: {after})\n{body}"

    def tools(self) -> list[Tool]:
        return [
            Tool("search_judgment", "find paragraphs of this judgment about some legal terms; "
                 "returns paragraph numbers with a short snippet", SearchArgs, self.search),
            Tool("read_paragraph", "read one paragraph in full, with the numbers of its "
                 "neighbours", ReadArgs, self.read_paragraph),
        ]


class PartyArgs(BaseModel):
    petitioner: str
    respondent: str
    year: int | None = Field(default=None, description="year of the citing draft, if known")


class CitationArgs(BaseModel):
    reporter: str = Field(description="SCR, SCC or AIR")
    year: int
    page: int


class TextArgs(BaseModel):
    query: str = Field(description="distinctive words from the case, e.g. a statute or doctrine")


class CaseArgs(BaseModel):
    case_id: str


_FTS_WORD = re.compile(r"[A-Za-z]{4,}")


class CaseFinder:
    """Find candidate judgments in the corpus. Used by the locator agent."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.seen: set[str] = set()  # case ids the model has been shown
        # The small serving database has no paragraph full-text index, so that tool is left out.
        self.has_text_index = con.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'paragraphs_fts'"
        ).fetchone() is not None

    def _line(self, case_id: str, title: str, year: int | None, extra: str = "") -> str:
        self.seen.add(case_id)
        return f"{case_id} | {title} | {year}{extra}"

    def by_party(self, a: PartyArgs) -> str:
        found = find_name_candidates(
            self.con, f"{a.petitioner} v. {a.respondent}", a.year, limit=5
        )
        if not found:
            return "No judgment with similar party names."
        return "\n".join(self._line(c.case_id, c.title, c.year, f" | name score {c.score:.2f}")
                         for c in found)

    def by_citation(self, a: CitationArgs) -> str:
        rows = self.con.execute(
            f"SELECT c.cnr, c.title, {DECISION_YEAR_SQL} FROM case_citations x "
            "JOIN cases c ON c.cnr = x.case_id WHERE x.reporter = ? AND x.year = ? AND x.page = ? "
            "LIMIT 5",
            (a.reporter.upper(), a.year, a.page),
        ).fetchall()
        rows += self.con.execute(
            f"SELECT c.cnr, c.title, {DECISION_YEAR_SQL} FROM citation_aliases x "
            "JOIN cases c ON c.cnr = x.case_id WHERE x.reporter = ? AND x.year = ? AND x.page = ? "
            "GROUP BY c.cnr LIMIT 5",
            (a.reporter.upper(), a.year, a.page),
        ).fetchall()
        if not rows:
            return "No judgment is recorded under that citation."
        return "\n".join(self._line(cnr, t, y) for cnr, t, y in dict.fromkeys(rows))

    def by_text(self, a: TextArgs) -> str:
        words = _FTS_WORD.findall(a.query.lower())[:8]
        if not words:
            return "Give at least one word of four letters or more."
        fts = " OR ".join(f'"{w}"' for w in words)
        rows = self.con.execute(
            f"SELECT c.cnr, c.title, {DECISION_YEAR_SQL}, COUNT(*) AS n FROM paragraphs_fts f "
            "JOIN paragraphs p ON p.rowid = f.rowid JOIN cases c ON c.cnr = p.case_id "
            "WHERE paragraphs_fts MATCH ? GROUP BY c.cnr ORDER BY n DESC LIMIT 5",
            (fts,),
        ).fetchall()
        if not rows:
            return "No judgment contains those words."
        return "\n".join(self._line(cnr, t, y, f" | {n} matching paragraphs")
                         for cnr, t, y, n in rows)

    def case_info(self, a: CaseArgs) -> str:
        row = self.con.execute(
            f"SELECT title, {DECISION_YEAR_SQL}, judges FROM cases c WHERE c.cnr = ?", (a.case_id,)
        ).fetchone()
        if row is None:
            return f"No case {a.case_id}."
        self.seen.add(a.case_id)
        return f"{a.case_id} | {row[0]} | {row[1]} | judges: {(row[2] or '')[:200]}"

    def tools(self) -> list[Tool]:
        tools = [
            Tool("find_by_party_names", "judgments whose party names resemble these",
                 PartyArgs, self.by_party),
            Tool("find_by_citation", "judgments recorded under a reporter citation",
                 CitationArgs, self.by_citation),
            Tool("case_info", "title, year and judges of one case id", CaseArgs, self.case_info),
        ]
        if self.has_text_index:
            tools.insert(2, Tool("find_by_text", "judgments whose text contains distinctive words",
                                 TextArgs, self.by_text))
        return tools
