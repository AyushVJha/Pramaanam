# PROMPTS.md — paste these into Claude Code, one milestone at a time

## Before you start (10 minutes, once)
1. Create an empty folder `pramaan/`, put **SPEC.md**, **CLAUDE.md** and this file inside, run `git init`.
2. Create a GitHub repo (public later, private for now).
3. In the Anthropic Console, set a monthly spend limit (e.g. $100) and create an API key. Put it in `.env` as `ANTHROPIC_API_KEY=...`.
4. Install `uv` and the AWS CLI (only needed for `--no-sign-request` downloads; plain HTTPS also works).
5. Open Claude Code in the folder.

**Habits that save money:** start a **new session for each milestone**; use plan mode for anything non-trivial; when a session gets long, ask Claude to write a short handoff note into `docs/HANDOFF.md`, then start fresh and tell it to read that note.

**Habits that make you interview-ready:** after each milestone, read the diff yourself, then ask: *"Quiz me on this milestone: 5 questions an interviewer would ask, one at a time, and grade my answers."*

---

## M0 — Scaffold + data inspection
```
Read SPEC.md and CLAUDE.md fully. Then propose a plan for Milestone M0 only:
1. Scaffold the repo layout from SPEC.md §7 (empty modules with docstrings), pyproject with uv, ruff, pytest, Makefile targets from CLAUDE.md, .gitignore, .env.example.
2. Write src/pramaan/data/download.py to fetch metadata parquet for years 2022–2024 and the English tar for ONE year (2023) from the public bucket indian-supreme-court-judgments (no credentials; HTTPS or aws --no-sign-request).
3. Write a notebook-free script scripts/inspect_metadata.py that prints: row counts per year; % empty for citation and nc_display; 30 random examples of citation, nc_display, title, petitioner, respondent; and a frequency table of citation formats detected by rough regex.
4. Extract text from 20 random 2023 PDFs with PyMuPDF and report: is text extractable, are paragraphs numbered, what do paragraph markers look like.
Write all findings into docs/DATA_NOTES.md with real examples and counts. Do not design the resolver yet. Show me the plan before writing code.
```
**You check:** open DATA_NOTES.md. Do you understand what `citation` contains? This decides the resolver design.

---

## M1 — Corpus database
```
Read SPEC.md §3.3–3.4 and docs/DATA_NOTES.md. Plan M1: build the SQLite corpus.
- pdf_text.py: PyMuPDF extraction keeping page numbers.
- paragraphs.py: split into numbered paragraphs using the markers found in DATA_NOTES.md; fall back to blank-line blocks when unnumbered. Unit tests with 3 fixture judgments.
- build_db.py: tables cases, case_citations, paragraphs, paragraphs_fts (FTS5), names_fts (FTS5 trigram tokenizer). Idempotent. Parse every known citation string from metadata into case_citations.
- make db-sample builds 2023 only; make db builds the configured year range.
- Print a summary: cases, paragraphs, % cases with zero paragraphs, % with a neutral citation.
Then spot-check 20 random judgments: print paragraph numbers and first 80 chars of each; flag bad splits. Record decisions in DECISIONS.md (why SQLite + FTS5).
```
**You check:** run `make db-sample`, open the DB with `sqlite3`, query a judgment you know.

---

## M2 — Citation extraction
```
Plan M2 from SPEC.md §4 step 1–2 and Appendix A.
- citations/patterns.py: one compiled regex per format (neutral, SCC, SCC OnLine, AIR, SCR, case-name). 
- citations/extract.py: returns pydantic Citation objects with raw, span, format, parsed fields, case_name, proposition (surrounding sentence(s)), quoted_text, para_ref.
- citations/normalise.py: parse into (reporter, year, volume, page) or (neutral_year, number); party-name normalisation (strip & Ors., & Anr., M/s, punctuation, case).
- tests/test_patterns.py: at least 30 real citation strings taken from judgments in our DB (not invented), plus tricky negatives.
- scripts/eval_extraction.py: I will hand-mark 100 citations in 10 judgments in bench/data/extraction_gold.jsonl (build me a tiny CLI to do this marking). Report precision/recall per format.
Show the plan first.
```
**You do:** the hand-marking (about 1 hour). This is your gold data — never let the AI label it for you.

---

## M3 — Resolver + identity check
```
Plan M3 from SPEC.md §4 steps 3–4.
- resolve/resolver.py: exact neutral → exact reporter (case_citations) → fuzzy party names + year (names_fts trigram candidates, rapidfuzz token_set_ratio rescoring). Return case_id, method, confidence, top-3 alternatives.
- checks/identity.py: compare the draft's case name and year to the resolved case; return match / mismatch with explanation.
- Build bench/data/resolve_dev.jsonl from real citing sentences in the corpus (cited case known), split dev/test now and freeze the split.
- Tune the fuzzy threshold on dev only; report accuracy per method and how often the fuzzy fallback is used. Add the SCC/AIR coverage limitation to DATA_NOTES.md with numbers.
```

---

## M4 — Quote and paragraph checks
```
Plan M4 from SPEC.md §4 steps 5–6.
- checks/quotes.py: for each quoted passage, sliding-window rapidfuzz partial_ratio over the resolved judgment's paragraphs; return best para_no, similarity, and a char-level diff for display.
- checks/paragraph.py: if para_ref given, check the quote/proposition is in that paragraph or within ±1.
- Tests: real quotes (should pass), altered quotes (one word changed, negation, spliced from two paragraphs) should fail with the right status.
```

---

## M5 — Support judge
```
Plan M5 from SPEC.md §4 step 7 and CLAUDE.md "LLM usage and cost".
- llm/client.py: Anthropic SDK wrapper with model from config, disk cache keyed by hash, token/cost logging to logs/llm_usage.jsonl, retry with backoff.
- llm/prompts.py: the support-judge prompt. Inputs: proposition, top-k paragraphs (with para numbers) from the resolved judgment only. Output strict JSON per SPEC.md. Instruct: quote evidence verbatim from supplied paragraphs or return cannot_determine.
- checks/support.py: retrieve top-k via paragraphs_fts BM25 on the proposition; call judge; validate JSON with pydantic; verify every evidence quote exists in the supplied paragraphs; retry once; else cannot_determine.
- pipeline.py + report.py + cli.py: `pramaan check draft.txt` prints the report table with statuses from SPEC.md §4.1.
Run on 10 dev items and show me cost per citation and latency.
```

---

## M6 — Benchmark v1
```
Plan M6 from SPEC.md §5.1–5.3.
- bench/build_correct.py: extract citing sentences from corpus judgments whose cited case resolves in-corpus; LLM pre-label relies_on vs distinguishes/overrules (cheap model, cached); keep relies_on candidates.
- bench/perturb.py: generate each synthetic error type from correct items; for non-existent, verify absence against the DB.
- bench/label_tool.py: a terminal UI showing proposition, cited case, evidence paragraphs; I choose the label and add a note. Saves to bench/data/gold.jsonl.
- Target ~400 items; I will hand-verify at least 150. Freeze dev/test split (stratified by error type). Draft the Hugging Face dataset card in bench/DATASET_CARD.md.
Never generate gold labels automatically; only suggestions that I confirm.
```
**You do:** label 150+ items yourself (2–3 sessions). Ask a law-trained friend to label a 50-item overlap if possible.

---

## M7 — Evaluation + baselines
```
Plan M7 from SPEC.md §5.4–5.5.
- bench/baselines.py: B0 (regex + exact lookup), B1 (LLM only, no retrieval), B2 (full pipeline), optional B3 ablation.
- bench/evaluate.py: per-error-type precision/recall/F1, macro-F1, existence-only metrics, support confusion matrix, cost per citation, median/p95 latency. Output docs/RESULTS.md tables from code (no hand-typed numbers).
- Run on dev first; show me; only then run once on test.
- docs/ERROR_ANALYSIS.md: 20 failures grouped by cause, with what we'd try next.
Estimate cost before running and ask.
```

---

## M8 — Natural hallucination study
```
Plan M8 from SPEC.md §5.2 (natural hallucinations).
- bench/natural.py: 100 Indian legal research questions (help me draft them; I will review), sent to each model I list in config with a fixed prompt; record model id, date, params.
- Extract citations from answers, run the pipeline, then I hand-label a sample (label_tool).
- Report per model: citations per answer, % NOT_FOUND_IN_CORPUS, % misrepresented among resolved, with confidence intervals and clear caveats about coverage.
```

---

## M9 — API, demo, deploy
```
Plan M9.
- api/app.py: FastAPI POST /check (text or file upload: .txt, .docx, .pdf) → report JSON; GET /health.
- demo/: [Gradio app on Hugging Face Spaces] OR [Next.js + Tailwind page calling the API] — ask me which.
- Report UI: one row per citation, colour by status, expandable evidence paragraphs, link to the judgment, disclaimer, dataset attribution.
- Deploy: Docker; DB downloaded from the Hugging Face dataset at startup. One-command local run.
- Add 3 example drafts (one clean, one with errors, one AI-generated) to demo/examples/.
```

---

## M10 — Launch
```
Plan M10.
- README.md: problem (2 lines + the Supreme Court ruling), one results table, demo link + GIF, quickstart (fresh clone → working in 5 commands), how it works diagram, limitations, attribution, licence.
- Check DECISIONS.md is complete.
- Fresh-clone test in a temp folder: follow README exactly; fix anything that breaks.
- Draft: LinkedIn post, a short blog post leading with the M8 finding, and a 2-minute demo video script.
```

---

## When stuck
- *"Explain what this module does as if to an interviewer, then list its 3 weakest points."*
- *"This test fails. Find the root cause before changing code; show me your reasoning."*
- *"Summarise what we've done this session into docs/HANDOFF.md so a fresh session can continue."*
