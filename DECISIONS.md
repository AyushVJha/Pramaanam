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
