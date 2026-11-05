#!/bin/sh
# Run the three v2 support modes one after another with whatever model .env selects.
# (A free hosted model finishes in minutes; a local one takes hours.)
cd "$(dirname "$0")/.." || exit 1
for mode in quote pointer agent; do
  PRAMAAN_SUPPORT_MODE=$mode uv run python bench/eval_support_v2.py 12 > "logs/v2_$mode.out" 2>&1
done
echo ALL_DONE > logs/v2_done.out
