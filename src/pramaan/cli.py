"""`pramaan check draft.txt` — run the pipeline on a draft and print the report table. (M5)"""

import argparse
import sqlite3
import sys
from pathlib import Path

from pramaan import config
from pramaan.pipeline import check_text
from pramaan.report import render_report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pramaan")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="verify the citations in a text file")
    check.add_argument("draft", type=Path)
    check.add_argument("--db", type=Path, default=config.DB_PATH)
    check.add_argument("--no-llm", action="store_true", help="skip the support check (free)")
    check.add_argument("--model", default=None, help="override the judge model from config")
    args = parser.parse_args(argv)

    if not args.db.exists():
        sys.exit(f"Database not found: {args.db}. Run `make db` first.")
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    text = args.draft.read_text(encoding="utf-8")
    reports = check_text(con, text, use_llm=not args.no_llm, model=args.model)
    print(render_report(reports))


if __name__ == "__main__":
    main()
