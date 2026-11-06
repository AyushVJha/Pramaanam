"""Compare support checkers on benchmark v2 (dev). (A6)

    PRAMAAN_SUPPORT_MODE=quote|pointer|agent PRAMAAN_JUDGE_BACKEND=ollama \
      PRAMAAN_JUDGE_MODEL=qwen3:8b uv run python bench/eval_support_v2.py [per_kind]

Modes: quote = the original single-shot judge (model copies quotes); pointer = single-shot, model
names paragraphs; agent = the reading agent (searches, reads, then answers).
`per_kind` caps items per kind (default 12), taken in file order, so every mode sees the same items.

Numbers printed, per kind (positives are NOISY, see build_support_v2.py):
- positive: accepted = judged supported/partially_supported;
- negatives (easy and hard): false_support = judged supported/partially_supported/contradicted,
  the dangerous error; safe = not_supported/cannot_determine;
- gave_up = no valid verified answer; median seconds, mean steps, total cost.
This is a dev yardstick. It is never run on test.
"""

import json
import os
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from pramaan import config
from pramaan.agents.support_agent import agent_support
from pramaan.checks.support import judge_support, judge_support_pointer

SPLIT = os.environ.get("PRAMAAN_SUPPORT_SPLIT", "dev")  # "test" only for the one frozen run
DATA = Path(f"bench/data/support_v2_{SPLIT}.jsonl")
ACCEPT = {"supported", "partially_supported"}
DANGEROUS = {"supported", "partially_supported", "contradicted"}


def main() -> None:
    per_kind = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    mode = os.environ.get("PRAMAAN_SUPPORT_MODE", "quote")
    model = config.JUDGE_MODEL
    items, count = [], defaultdict(int)
    for line in DATA.read_text().splitlines():
        item = json.loads(line)
        if count[item["kind"]] < per_kind:
            count[item["kind"]] += 1
            items.append(item)
    safe = model.replace("/", "_").replace(":", "_")
    cache = Path(f"logs/support_v2_{SPLIT}_cache_{mode}_{safe}" if SPLIT != "dev"
                 else f"logs/support_v2_cache_{mode}_{safe}")
    usage = Path("logs/llm_usage.jsonl")
    con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True) if mode == "agent" else None

    rows, start = [], time.perf_counter()
    for item in items:
        t0 = time.perf_counter()
        if mode == "agent":
            res = agent_support(con, item["case_id"], item["proposition"],
                                cache_dir=cache, usage_log=usage)
        else:
            judge = judge_support_pointer if mode == "pointer" else judge_support
            res = judge(item["proposition"], [tuple(p) for p in item["paragraphs"]],
                        cache_dir=cache, usage_log=usage)
        rows.append({"item_id": item["item_id"], "kind": item["kind"], "verdict": res.verdict,
                     "failure": res.failure, "steps": res.steps or res.attempts,
                     "cost": res.cost_usd, "seconds": round(time.perf_counter() - t0, 1)})
        print(f"{item['kind'][:6]:<7}{res.verdict:<20}steps={rows[-1]['steps']} "
              f"{rows[-1]['seconds']}s", flush=True)

    summary: dict = {"mode": mode, "model": model, "backend": config.JUDGE_BACKEND}
    for kind in ("positive", "easy_negative", "hard_negative"):
        k = [r for r in rows if r["kind"] == kind]
        if not k:
            continue
        summary[kind] = {"n": len(k), "gave_up": sum(r["failure"] is not None for r in k) / len(k)}
        if kind == "positive":
            summary[kind]["accepted"] = sum(r["verdict"] in ACCEPT for r in k) / len(k)
        else:
            summary[kind]["false_support"] = sum(r["verdict"] in DANGEROUS for r in k) / len(k)
            summary[kind]["safe"] = sum(r["verdict"] not in DANGEROUS for r in k) / len(k)
    summary["median_seconds"] = statistics.median(r["seconds"] for r in rows)
    summary["mean_steps"] = round(statistics.mean(r["steps"] for r in rows), 2)
    summary["total_cost_usd"] = round(sum(r["cost"] for r in rows), 4)
    summary["total_seconds"] = round(time.perf_counter() - start, 1)
    out = Path(f"logs/support_v2_{SPLIT}_{mode}_{safe}.json" if SPLIT != "dev"
               else f"logs/support_v2_{mode}_{safe}.json")
    out.write_text(json.dumps({"summary": summary, "rows": rows}))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
