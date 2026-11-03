.PHONY: setup data-sample db db-sample test lint bench-dev bench-test demo

setup:
	uv sync

data-sample:
	uv run python -m pramaan.data.download

db-sample:
	uv run python -m pramaan.data.build_db

db:
	uv run python -m pramaan.data.download --full
	uv run python -m pramaan.data.build_db --full

test:
	uv run pytest

lint:
	uv run ruff check .

bench-dev:
	uv run python bench/eval_resolve.py --split dev
	uv run python bench/eval_quotes.py --split dev
	@echo "(M3 resolver and M4 quote checks only. The full pipeline evaluation arrives in M7.)"

bench-test:
	uv run python bench/eval_resolve.py --split test
	uv run python bench/eval_quotes.py --split test
	@echo "(M3 and M4 only. Run on test once thresholds are fixed. Full pipeline in M7.)"

demo:
	@echo "demo: implemented in M9 (runs the web demo locally)"

# Load .env (if present) so PRAMAAN_* settings reach python.
-include .env
export
