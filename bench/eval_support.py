"""Score ONE judge model on the dev support set (bench/data/support_dev.jsonl). (M5)

Needs no database: every item carries its own top-5 paragraphs. Choose the model and server with
the same settings the pipeline uses:

    PRAMAAN_JUDGE_BACKEND=ollama PRAMAAN_JUDGE_MODEL=qwen3:8b uv run python bench/eval_support.py
    PRAMAAN_JUDGE_BACKEND=openai PRAMAAN_OPENAI_URL=http://127.0.0.1:8080 \
        PRAMAAN_JUDGE_MODEL=my-model uv run python bench/eval_support.py

What the numbers mean (positives are NOISY, see build_support_dev.py):
- positive_accept: positives judged supported/partially_supported (expected, not guaranteed);
- negative_reject: negatives judged not_supported/cannot_determine (the safe answer);
- false_support: negatives judged supported/partially_supported/contradicted (the dangerous error);
- gave_up: judge never produced a valid, verifiable answer (JSON or quotes failed twice).
Results go to logs/support_<model>.json. This is a dev yardstick, not a published result.
"""

import json
import statistics
import sys
import time
from pathlib import Path

from pramaan import config
from pramaan.checks.support import judge_support

DATA = Path("bench/data/support_dev.jsonl")
ACCEPT = {"supported", "partially_supported"}
SAFE_FOR_NEGATIVE = {"not_supported", "cannot_determine"}
DANGEROUS_FOR_NEGATIVE = {"supported", "partially_supported", "contradicted"}


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    items = [json.loads(line) for line in DATA.read_text().splitlines()]
    items = items[:limit] if limit else items
    model = config.JUDGE_MODEL
    safe_name = model.replace("/", "_").replace(":", "_")
    cache = Path(f"logs/support_cache_{safe_name}")  # per model, so models never share answers

    rows, start = [], time.perf_counter()
    for item in items:
        t0 = time.perf_counter()
        result = judge_support(
            item["proposition"], [tuple(p) for p in item["paragraphs"]],
            cache_dir=cache, usage_log=Path("logs/llm_usage.jsonl"),
        )
        rows.append({
            "item_id": item["item_id"], "kind": item["kind"], "verdict": result.verdict,
            "attempts": result.attempts, "failure": result.failure,
            "seconds": round(time.perf_counter() - t0, 2),
        })
        print(f"{item['kind'][:3]} {result.verdict:<20} attempts={result.attempts} "
              f"{rows[-1]['seconds']}s", flush=True)

    pos = [r for r in rows if r["kind"] == "positive"]
    neg = [r for r in rows if r["kind"] == "negative"]
    summary = {
        "model": model, "backend": config.JUDGE_BACKEND, "n_positive": len(pos),
        "n_negative": len(neg),
        "positive_accept": sum(r["verdict"] in ACCEPT for r in pos) / max(len(pos), 1),
        "negative_reject": sum(r["verdict"] in SAFE_FOR_NEGATIVE for r in neg) / max(len(neg), 1),
        "false_support": sum(r["verdict"] in DANGEROUS_FOR_NEGATIVE for r in neg)
        / max(len(neg), 1),
        "gave_up": sum(r["failure"] is not None for r in rows) / max(len(rows), 1),
        "needed_retry": sum(r["attempts"] == 2 for r in rows) / max(len(rows), 1),
        "median_seconds": statistics.median(r["seconds"] for r in rows),
        "total_seconds": round(time.perf_counter() - start, 1),
    }
    Path("logs").mkdir(exist_ok=True)
    out = Path(f"logs/support_{safe_name}.json")
    out.write_text(json.dumps({"summary": summary, "rows": rows}))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
