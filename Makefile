.PHONY: setup data-sample db db-sample test lint bench-dev bench-test demo

setup:
	uv sync

data-sample:
	uv run python -m pramaan.data.download

db-sample:
	@echo "db-sample: implemented in M1 (builds SQLite for year=2023 only)"

db:
	@echo "db: implemented in M1 (builds SQLite for the configured year range)"

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
