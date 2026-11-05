"""`pramaan check draft.txt` — run the pipeline on a draft and print the report table. (M5)"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

from pramaan import config
from pramaan.agents.orchestrator import DraftBudget, review_text
from pramaan.data.draft_reader import read_draft
from pramaan.pipeline import check_text
from pramaan.report import render_html, render_markdown, render_report, report_to_dicts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pramaan")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="verify the citations in a text file")
    check.add_argument("draft", type=Path)
    check.add_argument("--db", type=Path, default=config.DB_PATH)
    check.add_argument("--no-llm", action="store_true", help="skip the support check (free)")
    check.add_argument("--agents", action="store_true",
                       help="let the reading and locator agents work (slow with a local model)")
    check.add_argument("--agent-max-cost", type=float, default=1.0,
                       help="stop agents after this many dollars on one draft")
    check.add_argument("--model", default=None, help="override the judge model from config")
    check.add_argument("--format", choices=["text", "md", "html", "json"], default="text")
    check.add_argument("--out", type=Path, default=None, help="write the report here")
    args = parser.parse_args(argv)

    if not args.db.exists():
        sys.exit(f"Database not found: {args.db}. Run `make db` first.")
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        text = read_draft(args.draft)
    except (ValueError, OSError) as e:
        sys.exit(str(e))
    if args.draft.suffix.lower() == ".docx":
        print("Note: headers, footers and text boxes are not read.", file=sys.stderr)
    if args.agents:
        budget = DraftBudget(max_cost_usd=args.agent_max_cost)
        reports = review_text(con, text, budget, model=args.model)
    else:
        reports = check_text(con, text, use_llm=not args.no_llm, model=args.model)
    use_llm = not args.no_llm or args.agents
    model = (args.model or config.JUDGE_MODEL) if use_llm else None
    today = time.strftime("%Y-%m-%d")
    meta = {"source": args.draft.name, "date": today, "llm_used": use_llm, "model": model}
    if args.format == "md":
        output = render_markdown(reports, **meta)
    elif args.format == "html":
        output = render_html(reports, **meta)
    elif args.format == "json":
        output = json.dumps({**meta, "citations": report_to_dicts(reports)}, indent=2)
    else:
        output = render_report(reports)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
