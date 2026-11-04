# DECISIONS.md

Each entry: choice, alternative considered, why, trade-off.

## M0

### Shell out to `aws` CLI with `--no-sign-request` instead of `boto3`
- **Alternative:** add `boto3` as a dependency and call the S3 API directly.
- **Why:** the bucket is public and anonymous; SPEC.md §3.1 already names the CLI as the supported path, and `aws s3 cp` handles retries/resuming for large tar files for free.
- **Trade-off:** adds a system dependency (`awscli`) outside the Python environment, so `make setup` alone isn't enough on a machine without it — `download.py` checks for the binary and fails with an actionable error instead of downloading silently via HTTPS.

### Plan to key `cases` on `cnr`/`path`, not `case_id` (M1 design note, decided now because M0 found it)
- **Alternative:** use `case_id` from the metadata as the primary key, since it looks like an identifier.
- **Why:** `docs/DATA_NOTES.md` §2 found `case_id` is actually just the neutral citation with spaces (`"2023 INSC 1043"`), and it's empty for 4.7% of 2024 rows. `cnr` and `path` are 100% non-empty and 100% unique across all 2655 inspected rows.
- **Trade-off:** none really — just don't trust a field's name over its measured contents. Recorded here so M1's `build_db.py` doesn't repeat the mistake.

## M1

### SQLite + FTS5, not Postgres (SPEC.md §3.4)
- **Alternative:** Postgres with `pg_trgm` for fuzzy name matching and `pgvector` for future embedding search.
- **Why:** one file, no server to run or deploy, free to host (ships with the repo/HF dataset), and FTS5 gives BM25 ranking and a trigram tokenizer built in — enough for the resolver's exact + fuzzy lookups (M3) and the support judge's retrieval (M5) without standing up infra.
- **Trade-off:** no concurrent writers, no native vector index, weaker fuzzy-matching ergonomics than `pg_trgm`. At real scale (full corpus, concurrent API traffic) this would move to Postgres + `pg_trgm` + `pgvector`.

### `build_db.py` always rebuilds from scratch rather than upserting incrementally
- **Alternative:** diff against the existing DB and only insert/update changed rows.
- **Why:** PROMPTS.md's M1 "idempotent" requirement just needs re-running `make db`/`make db-sample` to produce the same result, not fast incremental updates — and dropping+recreating all tables is trivially correct (no stale-row bugs) at the corpus sizes this project targets (thousands, not millions, of cases).
- **Trade-off:** `make db` on the full 2010–2025 range always reprocesses everything, including PDF text extraction, which is the slow part. Acceptable for now; revisit if the full build becomes too slow to iterate on.

### Paragraph splitter: trust only a monotonic run of "N. " markers, not every regex hit
- **Alternative:** split on every line matching `^\d+\.\s`, as the naive approach M0 flagged.
- **Why:** docs/DATA_NOTES.md §4 found the naive regex also fires on stray page numbers and footnote refs. Requiring numbers to increase by exactly 1 across a run of >=3 lines, and discarding everything before the run starts (case header, HEADNOTES), fixed that — verified in `tests/test_paragraphs.py` against 3 real judgments.
- **Trade-off (measured, not guessed):** spot-checking 20 random 2023 judgments after `make db-sample` found **3/20 (15%) start at a paragraph number other than 1** — all 3 are judgments that extensively quote *other* cases' own numbered paragraphs (e.g. one quotes the *De Beers Consolidated Mines* tax-residency precedent's paragraph 8). When quoted material's numbering happens to form a longer monotonic run than the real judgment's true opening paragraphs, the splitter picks the longer run and silently drops the judgment's own early paragraphs (typically short procedural ones like "Leave granted."). This is a known, documented limitation, not a hidden one — see the `test_quoted_material_with_own_numbering_is_a_known_limitation` test and docs/DATA_NOTES.md. A fix (e.g. detecting quotation marks/indentation around the competing run) is future work, not M1 scope. **Consequence for M4:** a paragraph-reference check ("para 3") can false-negative on these ~15% of judgments if paragraph 3 was part of the discarded opening section.

## M2

### `build_db.py`'s SCR/neutral parsers moved into `citations/normalise.py`, not duplicated
- **Alternative:** leave M1's inline `_SCR_CITATION`/`_NEUTRAL_CITATION` regexes and parse functions where they were.
- **Why:** M2 needed the same parsing logic (plus SCC/SCC OnLine/AIR) in the module SPEC.md §7 actually designates for it. Rather than have two copies of SCR/neutral parsing drift apart, `build_db.py` now imports `parse_scr`/`parse_neutral` from `citations/normalise.py`.
- **Trade-off:** none measured — `make db-sample` was re-run after the refactor and produced byte-identical summary stats (856 cases, 17,002 paragraphs), confirming no regression.

### Test positives for SCC/SCC OnLine/AIR come from judgment *text*, not the `citation` metadata field
- **Alternative:** since M0 found zero SCC/AIR/SCC-OnLine citations in the `citation` metadata field, either fabricate test strings or skip real-data testing for those formats.
- **Why:** judgments cite *other* cases throughout their own body text, in every format — e.g. "Bhanu Kumar Jain vs. Archana Kumar, AIR 2005 SC 626 : (2005) 1 SCC 787" — even though the `citation` field only ever records a judgment's citation of *itself*. A corpus-wide scan found 3,445 real SCC strings, 458 real AIR strings, and 163 real SCC OnLine strings sitting in paragraph text. `tests/test_patterns.py`'s positives are pulled from this, not invented.
- **Trade-off:** none — this is strictly better than the fallback options, and resolved what looked like a real gap without fabricating anything.

### Case-name extraction: regex + heuristic filter only, no LLM fallback yet
- **Alternative:** build `llm/client.py` early (out of M2's planned order) to implement SPEC.md §4 step 1's LLM fallback for bare case-name mentions now.
- **Why:** Appendix A's case-name regex is explicitly "high recall, low precision by design." Building the LLM infrastructure a few milestones early, just to filter this one format, would be scope creep — a heuristic filter (bounded match width + capitalised-word-ratio check) measurably fixed the worst failures found on real text (e.g. "To cite a few judgments in this regard are Y.S. Jagan Mohan Reddy v. ..." no longer swallows the preceding clause) without new infrastructure.
- **Trade-off (known, not hidden):** residual false positives remain on real text — e.g. a judgment's own case-name header in its PDF text gets matched as if it were a citation to a different case, and some borderline matches with a short run of capitalized words still pass the 0.6 ratio threshold. `scripts/label_extraction.py` exists specifically to measure how often, rather than guessing; see docs/DATA_NOTES.md once that's run.

### Extraction-gold "recall" is a partial, structured-formats-only estimate — not full recall
- **Alternative:** have the user re-read all 10 judgments end-to-end to catch every citation `extract()` missed, for a true recall measurement.
- **Why:** PROMPTS.md estimates the whole hand-marking task at about 1 hour; a full re-read of 10 real judgments for exhaustive recall would take much longer. Instead, `label_extraction.py` does a cheap literal scan for "SCC"/"AIR"/"INSC"/"SCR" tokens *not* already covered by a candidate, and asks the user to judge just those regions — catching likely misses for the 5 structured formats without a full re-read.
- **Trade-off (stated plainly, not glossed over):** this cannot find a missed CASE_NAME citation (no reliable token to scan for), so `eval_extraction.py` always reports CASE_NAME recall as "not measured," never a guessed number. Structured-format recall is a lower bound, not exact — a miss with none of those 4 tokens nearby (unlikely for these formats, but possible) wouldn't be caught either.

### `pdf_text.py` strips running page header/footer print furniture, fuzzy-matched against the case's own party names
- **Alternative:** leave it as-is and rely on `label_extraction.py`'s human review to catch every occurrence as a one-off "incorrect" mark.
- **Why:** walking through the very first real example with the user surfaced a systematic bug, not a one-off: SCR print volumes carry a running page-top header ("SUPREME COURT REPORTS\n[YYYY] V S.C.R.") and a running footer that repeats the case's *own* title ("X v. Y"), and PyMuPDF's plain-text extraction interleaves both into the body text with no structural marker — so `citations/extract.py`'s CASE_NAME pattern was matching a judgment's own header/footer as if it cited a *different* case. The header is generic and stripped unconditionally (like the margin letters M0 found). The footer repeats the case's own name, so it's stripped only when a CASE_NAME-shaped match fuzzy-matches (rapidfuzz `token_set_ratio` >= 80, either party order) the case's *actual* petitioner/respondent from its own metadata — a citation to a genuinely different case (even one sharing a party name, e.g. the same company suing a different defendant in an earlier case) is left untouched.
- **Trade-off:** needed a second, unbounded-width case-name regex in `pdf_text.py` distinct from `citations/patterns.CASE_NAME` — the 8-word cap that protects `extract()`'s general-purpose matching from swallowing unrelated prose also truncated this footer's genuinely long corporate party name ("GODREJ AND BOYCE MANUFACTURING COMPANY LIMITED THROUGH ITS CONSTITUTED ATTORNEY"). Safe here because the match is gated by the fuzzy check against known names, not relied on for precision by itself. Measured impact: re-scanning 150 judgments after the fix found 0 remaining own-title leaks (previously a real, uncounted contributor to CASE_NAME false positives) — `make db-sample`'s paragraph count shifted from 17,002 to 16,960 as a result, which is expected, not a regression.

## Data storage (before M3)

### Full 1950–2026 corpus, not 2010–2025
- **Alternative:** keep SPEC's 2010–2025 range (6.3 GiB instead of 21.1 GiB English).
- **Why:** measured on the 2023 sample, 56% of cited authorities (SCC, AIR, SCR strings with a year) were decided before 2010 and 22% before 1990. A 2010+ corpus would mark most real citations "not found". The cost of the full range is only a one-off 21 GiB download.
- **Trade-off:** more disk and a longer first build. Measured only on one citing year (2023); re-check when more years are loaded.

### Three layers: raw archive on Drive, raw text layer, SQLite
- **Alternative:** keep only the SQLite DB, or keep raw tars on the laptop.
- **Why:** the laptop has too little free disk for 21 GiB, and PDF reading is the slow build step. Raw tars are copied once to Google Drive (verified, with a sha256 manifest), the per-page raw text is stored as zstd Parquet (13 MB for 2023 vs a 382 MB tar), and the DB is rebuilt from the text layer in seconds. The text layer stores raw text, not cleaned text, so cleaning rules can change without touching a PDF.
- **Trade-off:** one more storage layer to keep consistent. The extractor version is stored in each row so a PyMuPDF upgrade is detectable.

### rclone to Drive, not the Drive for Desktop folder
- **Alternative:** copy files into the synced Drive folder.
- **Why:** the desktop client caches uploads locally and could fill the laptop's remaining disk. rclone streams straight to Drive and `rclone check` verifies size and hash remotely.
- **Trade-off:** depends on an rclone login that can expire (it did once; fix is `rclone config reconnect gdrive:`).

### Resumable by construction, no separate state file
- **Alternative:** a progress file or database table of finished steps.
- **Why:** progress is read from the files themselves (raw present, manifest entry, text layer present), and files are written under a temporary name then renamed. A crash, internet drop or shutdown can never leave state that disagrees with disk. Network calls retry with backoff; after 5 failures the job exits non-zero and a service restarts it.
- **Trade-off:** a file that exists but is corrupt would be trusted. Mitigated for raw files by the hash check at archive time.

### Duplicate cases across year folders: keep the first copy
- **Found:** building the full 1950-2026 DB failed with a duplicate case ID. 5,181 cases are listed under two year folders, the decision year and the law-report volume year. The two rows are identical except for author_judge, available_languages and raw_html, none of which the DB uses.
- **Choice:** `build()` keeps the first copy it sees (years run oldest first, so this is the decision-year folder in 99.8% of cases) and skips the second, and logs how many it skipped.
- **Alternative:** key the table on (cnr, year) and keep both. Rejected: every query would need to dedupe, and the paragraphs would be stored twice.
- **Trade-off:** in the 0.2% of cases where the volume year comes first, `cases.year` is the volume year, not the decision year. The decision date is still stored in full.

### Indexes on the corpus DB (M3)
- **Choice:** add four indexes after the bulk insert: paragraphs by (case, paragraph number), case_citations by (reporter, year, volume, page), case_citations by case, and cases by year.
- **Alternative:** no indexes, since the DB is rebuilt and small. Rejected: the full corpus has 478,691 paragraphs, and a per-case paragraph query without an index scanned the whole table (a sanity query took over two minutes). The resolver does a citation lookup for every citation.
- **Trade-off:** a larger file and a slightly slower build. The DB is disposable and rebuilt from the text layer, so this costs nothing permanent.

### Resolver: fuzzy party names plus decision year, threshold 0.85 (M3)
- **Choice:** exact neutral and SCR lookup first. If that fails, or the citation is SCC, AIR or SCC OnLine, find candidates with the trigram index on distinctive words and rescore with rapidfuzz `token_set_ratio`, petitioner against petitioner and respondent against respondent. Accept a match at 0.85 or above. The year window is the decision year from two years before the cited year up to the cited year.
- **Alternative:** one embedding model over the whole title, or a single threshold with no year window. Rejected: names are short and full of "& Ors." noise, so character-level matching with a year filter is simpler to explain and run.
- **Why 0.85:** a dev-only sweep (`bench/tune_resolve.py`). Wrong-case answers stay at 1.2% at every threshold from 0.70 up, because the remaining wrong ones are same-party cases in neighbouring years. The threshold really trades correct answers against lookalike matches. From 0.80 to 0.85 it loses 2 points of correct answers for 5 points fewer lookalike matches. From 0.85 to 0.90 it loses 6.5 points for 4.4 points.
- **Refuse rather than guess:** a number shared by several cases, a near-tie that the report year cannot break, and a name with a party that is only "Ltd." or "Private Limited" all return no match, never a pick.
- **Year from the decision date, not the `year` column.** That column is the law-report volume year for 13% of cases. Using it hid correct matches (Kiran Singh, cited AIR 1954, is filed under 1955).
- **Trade-off:** same-party cases decided in nearby years (M.C. Mehta, Vidya Drolia, N.N. Global) cannot be fully separated by name and year. The report year tie-break picks the closest decision year, which is right more often than wrong on dev but can pick the wrong twin.

### Resolver benchmark: truth from parallel citations, not labels (M3)
- **Choice:** where a judgment writes "Name, (2001) 2 SCC 386 : [2001] 1 SCR 1", the SCR number identifies the case by exact lookup. We hide it and test the SCC citation plus the name. Split by a hash of the citing case id, 30% dev, 70% test, frozen. At most 3 items per cited case.
- **Alternative:** hand-labelling, or an LLM labelling. Rejected: too slow, and the resolver is what is under test.
- **Changed after looking at dev errors, before test was ever run:** pairing only across whitespace and colons, parallel numbers within two years of each other, and the case name must sit right before its citations. The first version paired footnote numbers with the wrong name in about a third of the items I inspected.
- **Unreliable class dropped:** items whose anchor number was not found are kept in the file as `anchor_not_found` but not scored. Reading the 8 on test showed 6 were the same case under a mistyped or garbled number. False matches are measured by leave-one-out instead: hide the true case and count how often a lookalike is returned.
- **Trade-off:** names are as the judgments write them, not as a language model would garble them, so the benchmark is easier than real hallucinated drafts. The hallucination benchmark comes in M6.

### Quote check: word-run index to locate, word-level score, threshold 85 (M4)
- **Choice:** reduce both texts to lowercase words, then (1) look for the quote word for word, including across a break between two neighbouring paragraphs; (2) otherwise find the best-aligned stretch with an index of shared four-word runs and score the share of agreeing words with rapidfuzz; (3) otherwise not found. A quote with "...." is checked piece by piece. Near matches list the changed words and flag a changed negation or number.
- **Alternative:** rapidfuzz `partial_ratio` over every paragraph, as SPEC.md describes. I tried it first. It ran over 10 minutes on one judgment, because the last numbered paragraph can hold 2.7 million characters. The index version takes 0.2 s.
- **Word level, not character level:** swapping one long word in a 13-word quote scored 87 at character level and fell under the threshold, though it is one changed word. A word-level score treats every word alike.
- **Why 85:** a dev-only sweep (`bench/tune_quotes.py`). It is the lowest threshold where spliced quotes are rejected 99% of the time. Below it, splices start passing as near matches.
- **Trade-off:** a score cannot tell an OCR slip from a deliberate change, so a near match is not a verdict. The diff and the negation and number flags carry the signal, and the support judge in M5 decides on meaning.
- **Known weakness, left unfixed on purpose:** pieces of fewer than four words after a "...." are ignored, so a real first half plus a short junk tail can pass as verbatim. I found it by reading test failures, so fixing it now would contaminate the test split. One of 1,166 altered test quotes hit it. Decide whether to fix it and re-measure on a fresh split.

### Quote benchmark: synthetic, truth by construction (M4)
- **Choice:** real quotes are sentences lifted from a judgment. Altered quotes are made from them mechanically: one word swapped, a negation added or removed, a number changed, two distant paragraphs spliced, or a sentence from another judgment. Same 30/70 hash split by case.
- **Alternative:** hand-labelling real misquotes. Not available yet. M6 adds realistic ones.
- **Trade-off:** it is easy. A "real" quote is copied from the very text the checker reads, so OCR and typing differences never appear. Near-perfect scores here say the logic works, not that real quotes will pass.

## Support judge (M5)

### One LLM function with cache, usage log and a pluggable backend
- **Choice:** every model call goes through `llm/client.py: complete()`. It checks a disk cache (sha256 of model, system, prompt, params), calls a backend object, and appends tokens, estimated dollars and latency to `logs/llm_usage.jsonl`. The real backend (`AnthropicBackend`) imports the `anthropic` package only when first used. Tests pass a fake backend.
- **Alternative:** call the SDK directly where needed. Rejected: CLAUDE.md requires caching and cost logging in one place, and tests would need the network.
- **Trade-off:** cost is an estimate from prices copied into `config.py`, not the bill. The cache means a repeated run is free but also means a changed prompt must change the key (it does, the prompt is part of the hash).
- **Not done yet:** the `anthropic` dependency is not added (CLAUDE.md says ask first, and the answer was to build offline first). `AnthropicBackend` is therefore written from the SDK documentation and has never run against the real API.

### Retrieval: BM25 over one judgment in Python, not FTS5
- **Choice:** after resolution, load that judgment's paragraphs and rank them with a 20-line BM25 (stopwords removed, each paragraph cut to 3,000 characters, paragraphs sharing no word with the proposition are dropped).
- **Alternative:** SPEC.md says BM25 via `paragraphs_fts`. I measured it: 2.8 to 3.0 s per query on the full corpus, because FTS5 scores matches across all 38k judgments before the `case_id` filter. The Python version is instant.
- **Why it is also better:** word weights come from this judgment alone, so a word that is rare in this case counts, even if common in the corpus.
- **Trade-off:** pure word overlap. A paragraph that makes the point in different words ranks low. Recall of the right paragraph in the top 5 is not measured yet; it needs the M6 benchmark.

### The judge is never believed without evidence
- **Choice:** the reply must be JSON that validates (pydantic). supported, partially_supported and contradicted need at least one evidence item, and every quote must occur, after the same lowercase-words normalisation as M4, in the paragraph it names. If not, one retry that tells the model what was wrong. After that: `cannot_determine`, with the failure recorded.
- **Alternative:** trust a well-formed answer. Rejected: a model can invent a convincing quote, and a verified-looking report with a fake quote is worse than no report.
- **Trade-off:** a correct verdict with a slightly paraphrased quote is rejected and costs a retry. We accept false `cannot_determine` over false confidence.

### Status mapping (provisional)
- Rules in `pipeline.py`: unresolved is NOT_FOUND_IN_CORPUS (the text says it does not mean fake); ambiguous number or a wrong year is NEEDS_REVIEW; name mismatch is NAME_MISMATCH; quote not found is MISQUOTE; quote only near is NEEDS_REVIEW; far paragraph is WRONG_PARAGRAPH; judge verdicts map to VERIFIED, UNSUPPORTED, CONTRADICTED, NEEDS_REVIEW. The first failing check decides, so later checks (and their cost) are skipped.
- **Provisional:** near match to NEEDS_REVIEW and the 0.7 identity threshold are guesses until M7 measures them.

### Judge model: start with the cheapest
- **Choice:** `claude-haiku-5-5` ($0.10 / $0.50 per million tokens), set in `config.py` and overridable by `PRAMAAN_JUDGE_MODEL` or `--model`. Effort `low`. No temperature is sent (newer models reject it).
- **Rule:** move to `claude-sonnet-5-5` only if Haiku fails on the dev set. Prompts and thresholds are tuned on dev only.
- **Not measured:** accuracy, cost per citation and latency of any real model. The numbers in the M5 plan were estimates.

### Open model by default: Ollama, no new dependency (M5)
- **Choice:** there is no budget for paid APIs, so the default judge is an open model served locally by Ollama (`qwen2.5:7b-instruct`, 4-bit, about 4.7 GB). `OllamaBackend` calls `http://localhost:11434/api/chat` with the standard library (`urllib`), so nothing is added to pyproject. Temperature 0 and JSON mode are on. Cost is logged as $0. The Anthropic backend remains one setting away (`PRAMAAN_JUDGE_BACKEND=anthropic`).
- **Alternative:** a free hosted tier. Rejected: rate limits, terms changes, and the benchmark would not be repeatable.
- **Trade-off:** a 7B model is weaker than a frontier model at legal reading, and the evidence-quote check is what protects us from its mistakes. Speed on a 16 GB M4 is unmeasured. Which open model is good enough is decided on dev only.

### SCC / AIR alias table mined from the judgments (resolver extension)
- **Choice:** add a table `citation_aliases` filled from parallel citations printed in judgments. The resolver tries it after exact SCR/neutral lookup and before fuzzy names. Conflicting evidence (two different cases for one number) is ignored. Each row keeps the judgment that printed it, so the benchmark can leave that judgment out.
- **Alternative:** buy or scrape a mapping (forbidden), or leave SCC/AIR to name matching only (85% on dev).
- **Why it is safe:** 99.0% precision on held-out judgments; 385 of 390 repeated numbers agree. Alias confidence is set to 0.99, which is that measured figure, not a guess.
- **Trade-off:** small. Only numbers that some judgment prints next to an SCR/neutral number are known (1,839 in the whole corpus), so most SCC/AIR citations still go to the fuzzy step. Dev accuracy 85.0% to 90.7%, test not yet run. Stale or mistyped numbers inside judgments become wrong rows; the conflict rule catches only repeats.
- **Schema change approved by the user** (CLAUDE.md rule). `build_db` now builds the table last; an older database without it still works, the step is skipped.

### Word input and the annexure report (product step)
- **Choice:** `pramaan check` reads .txt, .md and .docx (`python-docx`, added with the user's approval). Footnotes and endnotes are read from the docx XML with the standard library and appended after the body, because Indian drafts often keep citations there. The result can be written as text, Markdown, HTML or JSON (`--format`, `--out`). Markdown and HTML carry the disclaimer, a line saying which checks ran (and that the support check was not run, when so), and a legend of the statuses. HTML output is escaped.
- **Alternative:** PDF output and a Word add-in. Deferred: a PDF needs another dependency, and an add-in is a bigger product. Print the HTML to PDF in the meantime.
- **Local mode:** `--no-llm` makes no network call and sends nothing off the machine, which is what a lawyer with a confidential draft needs.
- **Limits:** headers, footers and text boxes in Word files are not read. Footnote reading was tested on a hand-built footnotes.xml in the standard Word format, not on a file saved by Word itself: try a real draft before relying on it.

### Web demo and API: FastAPI, local mode by default, nothing stored (M9 start)
- **Choice:** one FastAPI app (`pramaan.api.app`) with a plain HTML upload page (no JavaScript), `POST /report` (annexure as HTML), `POST /check` (JSON) and `GET /health`. Dependencies added with approval: fastapi, uvicorn, python-multipart; `httpx` is dev-only (test client). `make demo` runs it on 127.0.0.1:8000.
- **Privacy and safety defaults:** uploads are processed in a temp folder that is deleted at once; nothing is stored or logged. The AI support check is off unless the operator sets `PRAMAAN_ENABLE_LLM=1`, and a visitor must also tick it. Upload is capped at 2 MB and 60 citations. Unsupported files and corrupt Word files return a clean 400.
- **Alternative:** Gradio (fastest on Hugging Face Spaces, but a large dependency and less control over the report) or a Next.js front end (a second codebase).
- **Trade-off / not done:** no rate limiting yet, so a public host needs one in front; each request opens its own read-only database connection; the 1.6 GB database must be present on the host. The SPEC target "10 citations in under ~30 s" is not measured.

### Deployment packaging: download a checksummed database at start (deploy)
- **Choice:** the image does not contain the database. On start the app downloads a gzip of the serving database (327 MB; 1.29 GB unpacked, without the paragraph full-text index the app does not use), checks its sha256 before unpacking, and renames it into place. A per-client rate limit (10 uploads a minute) sits in front of the upload endpoints.
- **Alternative:** bake 1.3 GB into the image (slow builds and pushes, hits free-host size limits), or rebuild the database on the host (needs the 552 MB text layer and about 4 minutes).
- **Trade-off:** free hosts wipe the disk on restart, so each cold start re-downloads. The rate limit is in memory and per process, and trusts X-Forwarded-For if the host sets it: a speed bump, not security.
- **Not verified:** the Dockerfile has not been built, and no host has been tried.

### SCR Supplement citations get their own reporter, `SCR-SUPP` (data fix)
- **Choice:** `parse_scr` returns reporter `SCR-SUPP` (keeping year, volume, page) for citations with a "Supp" marker, in any of the forms `[1992] SUPP. 2 S.C.R. 1` (the dataset's own form), `[1992] Supp. (2) SCR 1`, `[1992] 2 Supp. SCR 1`. The resolver looks them up exactly like `SCR`, but only against `SCR-SUPP` rows. No schema change: `reporter` is a text column.
- **Alternative:** add a `series` column to `case_citations` (a schema change, so it needs approval), or keep one `SCR` reporter and add "supp" to the volume.
- **Why:** the Supplement series restarts its page numbers inside the same year and volume number as the regular series (22 clashing file-name pairs, DATA_NOTES 15). Before the fix the dataset's own Supplement form did not parse, so 7,641 cases (about 20%) had no SCR row, and a draft's "Supp. (2) SCR 1" lost its marker and volume and could match a regular-series case.
- **Trade-off:** one more reporter value to remember in the code (`_EXACT_METHOD`); older databases need a rebuild to gain the rows.

### Layout layer: Docling layout model + fresh Tesseract OCR, stored as typed blocks (re-plan step 4)
- **Choice:** every judgment is converted once into typed blocks per page (text, footnote, table, section_header, page_header, ...), with reading order and box, using Docling (layout model) with a full-page Tesseract read for the characters. Blocks go to `data/layout-v1/year=Y/blocks-N.parquet`, one line per finished judgment in `done.jsonl`, with the engine version and the PDF's sha256. Append-only: a new engine writes to a new folder, nothing is edited in place. Docling is an optional extra (`uv sync --extra layout`), not part of the web app.
- **Alternative:** keep the text embedded in the PDFs (what the DB is built from today); Tesseract alone; Docling on top of the embedded text.
- **Why:** on 39 blind pages (labels by Claude, not yet human-verified; DATA_NOTES 16) Docling + OCR had no page over 5% character error (embedded: 3 pages, Tesseract alone: 2), found footnotes and tables as separate blocks, and kept side notes out of the middle of body sentences. Docling on top of the embedded text was worse than the embedded text alone. Its running head also gives the printed page number, which pincites need.
- **Trade-off:** about 1.4 s per page, so the whole corpus (682,000 pages) takes about 1.5 days on 4 to 6 cores instead of minutes; adds torch (about 2 GB) to the dev environment; Docling drops list numbers ("iv.") and some small superscripts are misread. The OCR step is the slow part (the layout model alone is about 0.2 s per page), and running a different OCR engine later only means a new folder.
- **Not verified:** the result is only as good as my own transcriptions (no human check yet), and tables, footnotes and headings are not scored.

## Verdict semantics: VERIFIED only by deterministic proof (step 7)
- **Choice:** VERIFIED no longer needs the AI to say "supported". It means the citation is proven to exist (exact number, or SCC/AIR alias printed in >= 2 other judgments), name/year agree and quotes are verbatim. Negative statuses (NAME_MISMATCH, MISQUOTE, WRONG_PARAGRAPH, UNSUPPORTED, CONTRADICTED) are only asserted for a proven case; otherwise NEEDS_REVIEW "Possible X". Added LOW_FIDELITY_SOURCE (near-match with scan-noise-like differences) and CANNOT_VERIFY. The support check is advisory and can only downgrade.
- **Alternative:** keep VERIFIED = "AI says supported". Rejected: a small open model would be giving the green tick, which is the hallucination risk we are removing.
- **Why:** the source text is noisy (DATA_NOTES 15-16) and alias pairs can come from one typo, so accusing a lawyer needs proof.
- **Trade-off:** more NEEDS_REVIEW; VERIFIED says less (citation correct, not argument correct). Witness threshold (2) is a constant in pipeline.py, not tuned on test.

## Layout layer is on-demand, not whole-corpus
- **Choice:** stop the whole-corpus layout batch; convert only cited judgments (second reading) and evaluation samples.
- **Alternative:** build all 38k judgments (about 158 h on this laptop, measured in DATA_NOTES 17) or rent GPU/CPU time (costs money; company server needs approval).
- **Why:** a citation check touches a handful of judgments; precomputing everything buys little.
- **Trade-off:** first check of a judgment is slow (about 3 s per page); results are cached in the store, so repeats are instant.
