# Pramaan (प्रमाण)

An open benchmark and verification pipeline for citations to Indian Supreme Court judgments. See [SPEC.md](SPEC.md) for the full specification.

**Status:** Verdict redesign done (VERIFIED needs deterministic proof, AI is advisory only; docs/CLAIM_CONTRACT.md); layout layer being built for 2010-2024; not yet re-evaluated on dev. M4 (quote and paragraph checks) done on a synthetic benchmark: altered quotes are caught, but real quotes between judgments rarely match word for word because old cases carry OCR noise (docs/DATA_NOTES.md section 12). M3 resolver: 85.0% of SCC/AIR/SCC OnLine citations that carry a case name resolve to the right case on test before the SCC/AIR alias step; with it, 90.0% (600/667) on test, 0.9% wrong case. M2 labels are mostly Claude-labelled, not human gold. M5 (support judge) is built and tested with a fake model (`pramaan check draft.txt --no-llm` runs on the full corpus); no real LLM call has been made yet, so judge accuracy, cost and latency are not measured.


## Try it

```
uv sync
make demo                      # web page at http://127.0.0.1:8000 (needs pramaan.db: make db)
uv run pramaan check draft.docx --no-llm --format html --out report.html
```

Local mode (`--no-llm`) makes no network call. The AI support check is off by default.
