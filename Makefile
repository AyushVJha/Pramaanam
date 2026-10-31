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
	@echo "bench-dev: implemented in M7 (runs evaluation on the dev split)"

bench-test:
	@echo "bench-test: implemented in M7 (runs evaluation on the test split)"

demo:
	@echo "demo: implemented in M9 (runs the web demo locally)"

# Load .env (if present) so PRAMAAN_* settings reach python.
-include .env
export
