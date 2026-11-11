#!/bin/sh
# Run the plain-LLM baseline for several free models, one after another (dev items only).
# Models come from the endpoint in .env. A model that is closed or overloaded is skipped, not retried forever.
cd "$(dirname "$0")/.." || exit 1
for model in "$@"; do
  echo "== $model"
  # 20 minutes per model at most; a slow or overloaded model is reported as not completed
  PRAMAAN_LLM_RETRIES=1 PYTHONPATH=bench perl -e 'alarm shift; exec @ARGV' 1200 \
    uv run python bench/eval_baseline_llm.py --n 20 --model "$model" \
    > "logs/leaderboard_$model.txt" 2>&1 || echo "not completed: $model" | tee -a logs/leaderboard_incomplete.txt
done
echo ALL_DONE > logs/leaderboard_done.out
