# Pramaan — Specification

**Pramaan** (प्रमाण, "proof") is an open benchmark and verification pipeline for citations to Indian Supreme Court judgments. It answers one question for every case cited in a legal draft: *does this case exist, is it named correctly, is any quote accurate, and does the judgment actually support the proposition it is cited for?*

> Working name. Rename freely before launch; check GitHub, PyPI and Hugging Face for clashes first.

---

## 1. Why this project

### The problem
- On 2 July 2026, in *Pooja Ramesh Singh v. Jammu and Kashmir Bank Ltd.* (2026 INSC 668), the Supreme Court set aside tribunal orders that relied on AI-fabricated precedents. It called citing unverified AI-generated judgments misconduct by an advocate, and directed the Bar Council of India to form a committee.
- Earlier incidents: ITAT Bengaluru recalled an order citing non-existent judgments (Buckeye Trust, Dec 2024), and the Bombay High Court quashed a ₹27.9 crore tax assessment resting on three fake precedents (Oct 2025).
- The Supreme Court's draft AI regulations (June 2026) propose mandatory disclosure of AI use in filings.

### What already exists (so we don't build a me-too)
- **Manupatra Citation Verifier** (May 2026, paid Chrome extension): checks SCC, AIR, Neutral/INSC and SCR citations against Manupatra's database. Public material does not say it checks whether the case supports the proposition.
- **Pundora** (free citation check): looks up each citation and checks quoted words against the judgment. Its own comparison page says it does **not** catch a judgment cited for the opposite of its holding.
- **SCC Online, CaseMine, Indian Kanoon**: link and flag citations; no published accuracy for fabrication detection.
- **"Who Checks the Citations?" (arXiv 2606.21155, June 2026)**: a benchmark for legal hallucination detection on **US** federal briefs only. Taxonomy: non-existent citation, case-name mismatch, incorrect pincite, misquote, content misrepresentation. Finds models handle existence well but struggle with pincites and misrepresentation; free databases' incomplete coverage makes weak models treat "not found" as "fake".

### Our gap
1. **No public benchmark for Indian legal citation hallucinations.**
2. **No open tool that checks proposition support** (does the judgment hold what it is cited for) for Indian law, with published accuracy numbers.

Pramaan delivers both: a dataset on Hugging Face, an open-source verifier, a live demo, and a write-up with per-error-type results.

---

## 2. Scope

### In scope (v1)
- **Corpus:** Supreme Court of India judgments, English, from the open dataset (CC-BY-4.0). Start with a year range (e.g. 2010–2025) and expand only if time allows.
- **Citation formats:** Neutral (`2026 INSC 668`), SCC (`(2017) 10 SCC 1`), SCC OnLine (`2023 SCC OnLine SC 123`), AIR (`AIR 1973 SC 1461`), SCR (`[1950] SCR 88`, `(2019) 3 SCR 1`), and case-name-only mentions (`Kesavananda Bharati v. State of Kerala`).
- **Checks:** existence, identity (party names, year), quote accuracy, paragraph reference (where given), proposition support.
- **Interfaces:** Python library, CLI, FastAPI service, web demo.

### Out of scope (v1) — say so in the README
- High Court and tribunal judgments (PDFs often need OCR; add later).
- "Good law" status (overruled, distinguished). Note as future work.
- Statutes and sections.
- Legal advice of any kind. The tool reports evidence; a lawyer decides.

---

## 3. Data

### 3.1 Source
- GitHub: `vanga/indian-supreme-court-judgments`. Public S3 bucket `indian-supreme-court-judgments` (no AWS credentials needed: `--no-sign-request`).
- Layout:
  - `data/tar/year=YYYY/english/english.tar` (or `part-*.tar`) + `english.index.json` — judgment PDFs
  - `metadata/parquet/year=YYYY/metadata.parquet` — structured metadata
- Metadata fields: `title, petitioner, respondent, description, judge, author_judge, citation, case_id, cnr, decision_date, disposal_nature, court, available_languages, raw_html, path, nc_display, scraped_at, year`.
- Licence: CC-BY-4.0. **Attribute the dataset in the README and on the demo page.**

### 3.2 First task: inspect before designing (Milestone 0)
The README does not show example values for `citation` or `nc_display`. Before writing the resolver, download 2–3 years of metadata and record in `docs/DATA_NOTES.md`:
- What formats appear in `citation` (SCR? INSC? empty?) and how often it is empty.
- What `nc_display` contains (likely the neutral citation, for 2023+).
- How party names are written in `title`, `petitioner`, `respondent` (abbreviations, "M/s", "Ors.", "& Anr.").
- Whether PDFs have extractable text and paragraph numbers.

**Design consequence:** SCC and AIR are commercial reporters. If their citations are not in the metadata, the resolver must fall back to party-name + year matching. Measure how often that fallback is needed. This limitation is part of the write-up, not something to hide.

### 3.3 Processing
- Extract text with PyMuPDF. Keep page numbers.
- Split into numbered paragraphs (SC judgments usually number paragraphs). Store paragraph number, text, page.
- Normalise: Unicode NFKC, collapse whitespace, standardise quotes and dashes, keep the original too.

### 3.4 Storage: SQLite (deliberate choice)
- One file, reproducible, free to host, and FTS5 gives BM25 ranking built in.
- Tables (sketch):
  - `cases(case_id PK, title, petitioner, respondent, decision_date, year, judges, citation_raw, neutral_citation, pdf_path)`
  - `case_citations(case_id, reporter, year, volume, page, raw)` — every known citation string for a case, parsed
  - `paragraphs(case_id, para_no, page, text)`
  - `paragraphs_fts` — FTS5 virtual table over paragraph text (BM25)
  - `names_fts` — FTS5 with the `trigram` tokenizer over party names, for fuzzy candidate lookup; rescore with `rapidfuzz`
- Record in DECISIONS.md why SQLite over Postgres (portability, free deploy) and what you would change at scale (Postgres + pg_trgm + pgvector).

---

## 4. The verifier pipeline

Input: a draft (text, .docx or PDF). Output: one report row per citation.

```
draft ──► 1 Extract ──► 2 Normalise ──► 3 Resolve ──► 4 Identity ──► 5 Quote ──► 6 Paragraph ──► 7 Support ──► Report
```

1. **Extract.** Regex patterns per format (see Appendix A) + an LLM fallback for case-name-only mentions. For each citation capture: raw string, character span, case name if present, the **proposition** (the sentence(s) around it that the citation supports), any **quoted text**, any **paragraph reference**.
2. **Normalise.** Parse into `(reporter, year, volume, page)` or `(neutral year, number)`. Normalise party names (strip "& Ors.", "M/s", case, punctuation).
3. **Resolve.** In order: exact neutral citation → exact reporter citation from `case_citations` → fuzzy party names + year (trigram candidates, rapidfuzz `token_set_ratio`, threshold tuned on dev set). Output: matched `case_id` with a confidence, or none.
4. **Identity check.** Compare the draft's case name and year with the resolved case. Flag mismatches (right citation, wrong name, or the reverse).
5. **Quote check.** For each quoted passage, fuzzy-search the judgment's paragraphs (rapidfuzz `partial_ratio` over a sliding window). Report best match and similarity.
6. **Paragraph check.** If the draft cites "para 23", check the quote or proposition appears in or near paragraph 23.
7. **Support check.** Retrieve the top-k paragraphs **from the resolved judgment only** (BM25 via FTS5 on the proposition, optionally reranked by a small cross-encoder). An LLM judge reads the proposition plus those paragraphs and returns strict JSON:
   ```json
   {"verdict": "supported | partially_supported | not_supported | contradicted | cannot_determine",
    "evidence": [{"para_no": 23, "quote": "..."}],
    "reason": "one sentence"}
   ```
   Rules for the judge: it must quote evidence verbatim from the given paragraphs; if it cannot, verdict is `cannot_determine`. Validate the quotes programmatically (they must exist in the paragraphs) — reject and retry once otherwise.

**Key design decision:** retrieval is scoped to one judgment after resolution. No global vector index is needed, which keeps cost and latency low and removes cross-case confusion. Write this up in DECISIONS.md.

### 4.1 Report statuses (wording matters)
| Status | Meaning |
|---|---|
| `VERIFIED` | Resolved, identity matches, quotes found, judgment supports the proposition |
| `NOT_FOUND_IN_CORPUS` | Could not resolve. **Never label this "fake"**: it may be outside coverage (High Court, pre-range year, commercial-only citation) |
| `NAME_MISMATCH` | Citation resolves to a different case than the name given |
| `MISQUOTE` | Quoted text not found in the judgment (show the closest match) |
| `WRONG_PARAGRAPH` | Content exists but not at the cited paragraph |
| `UNSUPPORTED` / `CONTRADICTED` | Judgment does not support, or states the opposite of, the proposition |
| `NEEDS_REVIEW` | Low confidence anywhere in the chain |

Every row links to the judgment and shows the evidence paragraphs.

---

## 5. The benchmark (PramaanBench)

### 5.1 Error taxonomy (adapted from arXiv 2606.21155)
1. **Non-existent case** — citation and/or name that matches no judgment.
2. **Name mismatch** — real citation, wrong case name (or the reverse).
3. **Wrong citation details** — right case, wrong year/volume/page/neutral number.
4. **Misquote** — quoted words not in the judgment, or materially altered.
5. **Misrepresented holding** — real case, but it does not support (or contradicts) the proposition.
Plus a **correct** class.

### 5.2 Building the items
- **Correct items (free and real):** SC judgments cite earlier SC judgments. Extract citing sentences from judgments in the corpus, resolve the cited case, and keep pairs where the cited case is in the corpus. The citing sentence is the proposition. Use an LLM to pre-label whether the citing context *relies on* the case (vs. distinguishes or overrules it), then hand-check.
- **Synthetic errors:** perturb correct items:
  - non-existent: generate plausible but absent citations (check absence against the corpus) with plausible names
  - name mismatch: swap names between two real citations
  - wrong details: change year/volume/page/number
  - misquote: edit quoted text (change a key word, negate, splice)
  - misrepresentation: attach a proposition from a different case on a similar topic, or negate the holding
- **Natural hallucinations (the headline):** ask several LLMs ~100 Indian legal research questions (e.g. "Which Supreme Court judgments establish X? Cite them."). Extract every citation, run them through the pipeline, then hand-label a sample. Report the fabrication and misrepresentation rate per model. Use only models you can legitimately access (your Claude credits; free tiers of others; open models locally). State exactly which models, versions and dates.

### 5.3 Size and labels
- Target ~400 items: ~150 correct, ~50 per error type, plus the natural-hallucination set.
- **Gold labels:** hand-verify at least 150 items yourself, ideally with a law-trained friend labelling a 50-item overlap; report agreement (Cohen's kappa).
- Splits: `dev` (tune thresholds and prompts) and `test` (touch only for final numbers). Never tune on test.
- Publish on Hugging Face with a dataset card: sources, licence, construction method, known biases, label quality.

### 5.4 Metrics
- Per error type: precision, recall, F1. Overall macro-F1.
- Existence detection on its own (so results compare with simpler tools).
- Support check: confusion matrix over verdicts.
- Cost per citation (₹/$) and median and p95 latency.
- Error analysis: 20 worked failures, grouped by cause.

### 5.5 Baselines
- **B0** regex extraction + exact lookup only (what a basic checker does).
- **B1** LLM only, no retrieval: "Is this citation real, and does it support the claim?"
- **B2** full Pramaan pipeline.
- **B3 (optional)** B2 + cross-encoder rerank, or a larger judge model — as an ablation.
- **External (optional, manual, small):** run ~30 test items through Pundora's free checker by hand and report. Check their terms first; do not automate or scrape any third-party service.

---

## 6. Tech stack
- Python 3.11+, `uv` for environments, `ruff` + `pytest`.
- PyMuPDF (text), `rapidfuzz` (fuzzy matching), SQLite FTS5 (BM25), `pydantic` (schemas), `anthropic` SDK (judge; model names in config).
- Optional: `sentence-transformers` cross-encoder for rerank.
- FastAPI for the API; web demo either Gradio on Hugging Face Spaces (fastest) or Next.js + Tailwind (doubles as Next.js practice).
- `python-docx` for .docx input.

## 7. Repository layout
```
pramaan/
  CLAUDE.md  SPEC.md  PROMPTS.md  README.md  DECISIONS.md
  docs/DATA_NOTES.md  docs/RESULTS.md  docs/ERROR_ANALYSIS.md  docs/DEFENSE.md  docs/HANDOFF.md
  pyproject.toml  .env.example  Makefile
  scripts/       inspect_metadata.py  eval_extraction.py
  src/pramaan/
    config.py
    data/        download.py  pdf_text.py  paragraphs.py  build_db.py
    citations/   patterns.py  extract.py  normalise.py
    resolve/     resolver.py  names.py
    checks/      identity.py  quotes.py  paragraph.py  support.py
    llm/         client.py  prompts.py  cache.py
    report.py    pipeline.py  cli.py
    api/         app.py
  bench/
    build_correct.py  perturb.py  natural.py  label_tool.py  evaluate.py  baselines.py
    data/        (generated; not committed if large)
  tests/         test_patterns.py  test_resolver.py  test_quotes.py  test_support_schema.py ...
  demo/          (Gradio app or Next.js app)
```

## 8. Milestones and acceptance criteria

| # | Milestone | Done when |
|---|---|---|
| M0 | Data inspection | `DATA_NOTES.md` answers every question in §3.2 with counts and examples |
| M1 | Corpus DB | SQLite built for the chosen year range; `make db` is reproducible; paragraph split verified on 20 random judgments |
| M2 | Extraction | Patterns for all formats; ≥30 unit tests from real strings; precision/recall measured on 100 hand-marked citations |
| M3 | Resolver + identity | Exact and fuzzy resolution; threshold tuned on dev; resolution accuracy reported |
| M4 | Quote + paragraph checks | Tests with real and altered quotes |
| M5 | Support judge | Strict JSON, evidence validation, retry, caching; cost per call logged |
| M6 | Benchmark v1 | ~400 items, 150+ hand-verified, splits frozen, dataset card drafted |
| M7 | Evaluation | B0–B2 run on test; `RESULTS.md` with tables; `ERROR_ANALYSIS.md` with 20 failures |
| M8 | Natural hallucination study | Per-model rates with method and dates |
| M9 | API + demo + deploy | Live URL; upload a draft → report in under ~30 s for 10 citations |
| M10 | Launch | README, DECISIONS, demo video, HF dataset, blog post |

Rough timing: M0–M2 week 1, M3–M5 week 2, M6–M7 week 3, M8–M10 week 4.

## 9. Budget ($100 Claude credits)
- Build with Claude Code: ~$55–60. Use the default model for most work; switch to a stronger model only for hard design or debugging. Start fresh sessions per milestone.
- Benchmark judge runs: ~$25–30. Use the cheapest capable model as judge; cache every LLM call by hash; use batch processing for bulk runs; never re-run unchanged items.
- Buffer: ~$10. Set a spend limit in the Anthropic Console.
- Everything else free: local PDF parsing, SQLite, local cross-encoder, Hugging Face hosting.

## 10. Quality bar (what reviewers check)
- Fresh clone → `uv sync` → `make db-sample` → `make test` → `make demo` works.
- README leads with the problem, one result table, the demo link, and limitations.
- DECISIONS.md: each major choice, the alternative, why, and the trade-off.
- Honest limits: coverage, SCC/AIR mapping, judge errors, label noise.
- No secrets in the repo; `.env.example` only.

## 11. Ethics and legal
- Attribute the CC-BY-4.0 dataset.
- Disclaimer on every report: "Automated check, not legal advice. Verify against an authorised source."
- Never call a citation "fake" when it is merely not found.
- Do not scrape Indian Kanoon, SCC Online, Manupatra or any paid service.
- Keep this completely separate from TurtleLabs/LKS code, data and clients. Check your employment contract's IP clause before publishing.

## 12. Launch plan
- Hugging Face dataset + GitHub repo + live demo + 2-minute video.
- Blog post / LinkedIn post leading with the natural-hallucination finding and the method.
- Share with Indian legal-tech teams (Manupatra, Pundora, CaseMine, Jhana, Lucio, SpotDraft), law-firm innovation leads, and legal news outlets (LiveLaw, Bar & Bench).
- Optional: short arXiv paper extending arXiv 2606.21155's taxonomy to India.

---

## Appendix A: starting regex shapes (refine against real data)
- Neutral: `\b(19|20)\d{2}\s+INSC\s+\d{1,5}\b`
- SCC: `\(\s*(19|20)\d{2}\s*\)\s*\d{1,2}\s+SCC\s+\d{1,4}`
- SCC OnLine: `\b(19|20)\d{2}\s+SCC\s+OnLine\s+SC\s+\d{1,5}\b`
- AIR: `\bAIR\s+(19|20)\d{2}\s+SC\s+\d{1,5}\b`
- SCR: `[\[\(]\s*(19|20)\d{2}\s*[\]\)]\s*(\d{1,2}\s+)?(Supp\.?\s*)?(\(\d\)\s*)?S\.?C\.?R\.?\s+\d{1,4}`
- Case name: `[A-Z][\w.&,'\- ]+?\s+v(?:s)?\.?\s+[A-Z][\w.&,'\- ]+` (high recall; filter with LLM or heuristics)

## Appendix B: references
- AI-hallucinated case law in India (iPleaders): https://blog.ipleaders.in/ai-hallucinated-case-law-fake-citations-india/
- Who Checks the Citations? (arXiv 2606.21155): https://arxiv.org/html/2606.21155v2
- Manupatra Citation Verifier (PTI via The Wire): https://m.thewire.in/article/ptiprnews/manupatra-ai-launches-citation-verifier-to-tackle-fake-and-inaccurate-legal-citations-in-the-age-of-ai
- Pundora tool comparison: https://pundora.in/compare-legal-research-databases-india
- SC judgments dataset: https://github.com/vanga/indian-supreme-court-judgments
- SC neutral citation launch (Bar & Bench): https://www.barandbench.com/news/supreme-court-launches-neutral-citation-judgments
- Stanford HAI on legal RAG hallucinations: https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-queries
