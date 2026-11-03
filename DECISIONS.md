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
