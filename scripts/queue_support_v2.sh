#!/bin/sh
# Wait for the v1 pointer run, then run the three v2 modes one after another (free, local model).
cd "$(dirname "$0")/.." || exit 1
while pgrep -f "bench/eval_support.py" >/dev/null; do sleep 30; done
for mode in quote pointer agent; do
  PRAMAAN_SUPPORT_MODE=$mode PRAMAAN_JUDGE_BACKEND=ollama PRAMAAN_JUDGE_MODEL=qwen3:8b \
    uv run python bench/eval_support_v2.py 12 > logs/v2_$mode.out 2>&1
done
