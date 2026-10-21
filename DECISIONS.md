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
