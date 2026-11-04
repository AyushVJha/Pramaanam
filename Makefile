.PHONY: bench-text-layer bench-pipeline-quotes bench-pipeline invariants setup data-sample db db-sample test lint bench-dev bench-test demo

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
	uv run uvicorn pramaan.api.app:app --host 127.0.0.1 --port 8000

# Load .env (if present) so PRAMAAN_* settings reach python.
-include .env
export

invariants:
	uv run python scripts/check_invariants.py

bench-pipeline:
	uv run python bench/eval_pipeline.py --split dev

bench-pipeline-quotes:
	uv run python bench/eval_pipeline_quotes.py --split dev

bench-text-layer:
	uv run python -m bench.eval_text_layer_pages
