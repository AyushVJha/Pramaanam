"""Run the checker (AI off) on real, publicly reported fabricated citations.

Items live in bench/real_fakes/items.jsonl, each with a public source. This is NOT a
benchmark of the held-out test split: it is six items, used only to see what the checker
does with fabrications that really happened. Nothing is tuned on it.

  uv run python bench/eval_real_fakes.py            # writes bench/results/real_fakes.json
"""

import json
import sqlite3
from pathlib import Path

from pramaan import config
from pramaan.pipeline import check_text

ITEMS = Path("bench/real_fakes/items.jsonl")
OUT = Path("bench/results/real_fakes.json")


def main() -> None:
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    rows = []
    for line in ITEMS.read_text().splitlines():
        item = json.loads(line)
        reports = check_text(con, item["text"], use_llm=False)
        statuses = [r.status for r in reports]
        rows.append({**item, "statuses": statuses,
                     "reasons": [r.reason for r in reports]})
    nonexistent = [r for r in rows if r["kind"] == "reported_nonexistent"]
    summary = {
        "items": len(rows),
        "reported_nonexistent": len(nonexistent),
        "reported_nonexistent_marked_VERIFIED": sum(
            "VERIFIED" in r["statuses"] for r in nonexistent),
        "status_counts": {s: sum(s in r["statuses"] for r in rows)
                          for s in sorted({s for r in rows for s in r["statuses"]})},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "items": rows}, indent=2))
    for r in rows:
        print(f"{r['id']:24} {r['kind']:30} {r['statuses']}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
