# Pramaan (प्रमाण)

An open benchmark and verification pipeline for citations to Indian Supreme Court judgments. See [SPEC.md](SPEC.md) for the full specification.

**Status:** Working prototype: CLI and web demo run on the full corpus (0.9 s for a 3-citation draft with the AI check off). VERIFIED needs deterministic proof and the AI check is advisory only (docs/CLAIM_CONTRACT.md). On the resolver benchmark, dev split, 0 of 246 citations were VERIFIED on a wrong case (`make bench-pipeline`); coverage is a floor of 34 VERIFIED. AI check, local qwen3:8b via Ollama, dev set of 39 items (positives are noisy, `logs/support_qwen3_8b.json`): 0 of 15 negatives judged supported, 41.7% of 24 positives accepted, 20.5% gave no valid answer, median 45 s per item on this laptop, so too slow for interactive use. Test split not run. Layout second reading is built but converts judgments on demand (a whole-corpus run needs ~158 h on a laptop). Docker image never built. Fresh-clone check (2026-11-05): `uv sync`, `make data-sample` (28 s), `make db-sample` (67 s, 2023 only), `make test` (218 passed, 1 skipped without the layout extra), `make lint` and `pramaan check` all ran from a new clone. M4 (quote and paragraph checks) done on a synthetic benchmark: altered quotes are caught, but real quotes between judgments rarely match word for word because old cases carry OCR noise (docs/DATA_NOTES.md section 12). M3 resolver: 85.0% of SCC/AIR/SCC OnLine citations that carry a case name resolve to the right case on test before the SCC/AIR alias step; with it, 90.0% (600/667) on test, 0.9% wrong case. M2 labels are mostly Claude-labelled, not human gold. M5 (support judge) is built and tested with a fake model (`pramaan check draft.txt --no-llm` runs on the full corpus); no real LLM call has been made yet, so judge accuracy, cost and latency are not measured.


## Try it

```
uv sync
make demo                      # web page at http://127.0.0.1:8000 (needs pramaan.db: make db)
uv run pramaan check demo/sample_draft.txt --no-llm
uv run pramaan check draft.docx --no-llm --format html --out report.html
```

Local mode (`--no-llm`) makes no network call. The AI support check is off by default.
