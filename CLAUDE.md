# CLAUDE.md — standing instructions for this repo

You are helping Ayush build **Pramaan**: an open benchmark and verifier for citations to Indian Supreme Court judgments. **SPEC.md is the source of truth.** Read it at the start of every session, along with DECISIONS.md and the latest notes in docs/.

## Who you're working with
- Ayush is an AI engineer with one year of production experience (Go, Python, Postgres, LLM extraction). He must be able to **explain and defend every line in an interview**.
- So: prefer simple, readable code over clever code. When you make a non-obvious choice, explain it in two or three sentences and add an entry to DECISIONS.md (choice, alternative, why, trade-off).
- At the end of each milestone, append five likely interview questions with short answers about that milestone to `docs/DEFENSE.md`.

## How to work
1. **Plan briefly, then proceed.** For any task larger than a small fix, write a short plan (files, functions, tests) and carry on without waiting for approval (Ayush's instruction, 4 Nov 2026). Stop and ask only for outward-facing or irreversible actions: posting publicly, hosting, buying domains, spending money, the company server, the test split, the employment IP clause.
2. **One milestone at a time** (SPEC.md §8). Don't start the next milestone's work early.
3. **Small steps.** Write a function, write its test, run it, then move on. Keep diffs reviewable.
4. **Run things.** After changes, run `make test` (or the relevant pytest) and `ruff check`. Never claim something works without running it.
5. **Log, don't block**, when adding a dependency or changing the DB schema: choose the best option, add a DECISIONS.md entry (choice, alternative, why, trade-off), keep it reversible. Do not change the benchmark splits or the human-verified labels without a recorded reason.
6. **Commit** at each green step with a clear message (`feat(resolver): fuzzy party-name match with trigram candidates`).

## Hard rules
- **Never fabricate data, labels, results or numbers.** Every number in README/RESULTS.md must come from a script in this repo that can be re-run. If something wasn't measured, say "not measured".
- **Never tune on the test split.** Thresholds and prompts are tuned on `dev` only.
- **"Not found" is not "fake".** Use the status names in SPEC.md §4.1 exactly.
- **No scraping** of Indian Kanoon, SCC Online, Manupatra, Pundora or any paid/third-party service. Data comes only from the open CC-BY-4.0 Supreme Court dataset.
- **No TurtleLabs/LKS code, data, prompts or client material**, ever.
- **No secrets in git.** Keys live in `.env` (gitignored); keep `.env.example` updated.

## LLM usage and cost
- All LLM calls go through `src/pramaan/llm/client.py`, which: reads the model name from config, caches responses on disk keyed by a hash of (model, prompt, params), logs tokens and estimated cost per call to `logs/llm_usage.jsonl`.
- Default to the cheapest model that passes the dev set. Use batch processing for bulk benchmark runs.
- Before any run expected to cost more than $2, print the estimate and ask.
- Judge outputs must be strict JSON validated with pydantic; evidence quotes must be verified to exist in the supplied paragraphs. Retry once, then return `cannot_determine`.

## Code conventions
- Python 3.11+, `uv`, type hints everywhere, pydantic models for data that crosses module boundaries.
- `ruff` for lint/format, `pytest` for tests. Tests use small fixture files in `tests/fixtures/`, never the full corpus.
- Pure functions where possible; I/O at the edges (`data/`, `api/`, `cli.py`).
- Logging, not print, outside the CLI.

## Commands (keep the Makefile in sync)
- `make setup` — `uv sync`
- `make data-sample` — download a small year range for development
- `make db` / `make db-sample` — build SQLite from downloaded data
- `make test` — pytest
- `make lint` — ruff
- `make bench-dev` / `make bench-test` — run evaluation on a split
- `make demo` — run the web demo locally

## Definition of done (every milestone)
- Acceptance criteria in SPEC.md §8 met and demonstrated by a command.
- Tests pass, lint clean.
- DECISIONS.md and docs/DEFENSE.md updated.
- README "Status" section updated in one line.
