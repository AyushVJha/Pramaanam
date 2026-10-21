# DEFENSE.md — interview questions per milestone

## M0 — Data inspection

**1. Why did you inspect the data before writing any extraction/resolver code?**
Because SPEC.md's own README reference didn't document what `citation` and `nc_display`
actually contain, and the resolver design (exact match vs. fuzzy fallback) depends entirely
on that. Guessing the format and writing a resolver against the guess would have meant
redoing it once the real data surfaced — cheaper to spend an hour measuring first. It also
caught a real bug-in-waiting: `case_id` isn't an opaque key, it's the neutral citation
re-formatted, and it's sometimes empty.

**2. You found zero SCC/AIR citations in the metadata for 2022-2024. What does that mean for
the resolver, and how would you verify it holds for other years?**
It means the exact-match resolution path (M3) only works for SCR and neutral (INSC)
citations out of this metadata; any SCC/AIR citation in a draft has to fall through to the
fuzzy party-name+year path, and I need to measure how often that happens once the resolver
exists. It does *not* mean SCC/AIR citations don't exist for Supreme Court cases generally —
neutral citations only started in 2023, and the SCR series the bucket's metadata draws from
may not go back as far either, so older years could show a different mix. I flagged this
explicitly in DATA_NOTES.md §5 as unverified, rather than assuming 2022-2024's pattern holds.

**3. Why key the `cases` table on `cnr`/`path` rather than `case_id`?**
Measured, not assumed: across all 2655 inspected rows, `case_id` is literally
`nc_display` with spaces inserted (zero mismatches), and it's empty for 4.7% of 2024 rows —
so it's neither a stable identifier nor always present. `cnr` and `path` are 100% non-empty
and 100% unique in the same sample. Using `case_id` as a primary key would have produced
NULL/duplicate keys the moment the DB included a case missing its neutral citation.

**4. Your paragraph-marker regex has false positives. Why ship DATA_NOTES.md with that
regex instead of fixing it now?**
M0's job is to characterize the data, not build the paragraph splitter — that's M1. The
honest thing was to run the rough regex from PROMPTS.md, report that it worked for 20/20
PDFs but flag the 2 false positives I actually saw (`'142'`, `'366'` picked up as
"paragraphs"), and let that finding shape M1's design (e.g. require near-1 start and
monotonic increase) rather than silently patching the regex and hiding that the naive
version doesn't quite work.

**5. Why `aws s3 cp --no-sign-request` instead of adding `boto3`?**
The bucket is already public/anonymous, SPEC.md names the CLI path as the supported route,
and the CLI gives retry/resume for the ~400MB tar for free. The cost is a system dependency
outside the Python env (`awscli`), which `download.py` checks for explicitly and fails loudly
on rather than silently falling back to an unauthenticated HTTPS GET with no retry logic.

## M1 — Corpus database

**1. Your paragraph splitter misses the opening paragraphs on 15% of a 20-judgment
spot-check. Why ship it instead of fixing it?**
Because the failure mode is well understood and narrow: it only happens when a judgment
quotes another case's own numbered paragraphs at length, and the quoted numbering happens
to form a longer monotonic run than the judgment's real (but short) opening sequence. I
measured the rate (3/20) rather than guessing, wrote a test that locks in and explains the
exact behavior on a real example (`2023_15_848_865_EN.pdf`, quoting an affidavit's own
"4.-7." numbering), and documented the downstream consequence for M4 (a cited "para 3"
could false-negative if paragraph 3 was in the discarded opening section). Engineering a
perfect fix — e.g. detecting quotation marks/indentation to disambiguate — is future work,
not something M1's acceptance criteria asked for.

**2. Why key `case_citations`/`paragraphs` on a column literally named `case_id` when
M0 told you not to trust that name?**
Because that's the column *name* SPEC.md §3.4's schema sketch uses for the foreign key,
not the metadata field I was warned about. I kept the name for spec fidelity but populate
it with `cnr` (the real stable key), and said so explicitly in a code comment and in
DECISIONS.md — the point of the M0 finding was "don't trust `case_id`'s *contents*", not
"never use that identifier as a name."

**3. Two cases ended up with zero paragraphs. How did you know that was a real data gap
and not a bug in your extraction code?**
I didn't assume — I checked. Both cases' derived PDF filenames weren't present in
`english.tar`'s member list, and the tar's own `english.index.json` reports
`file_count: 854` against 856 metadata rows — exactly a 2-row gap. If it had instead been
a PyMuPDF exception or an empty-but-present PDF, the `_case_paragraphs` exception handler
would have logged a warning with a traceback, which it didn't for these two.

**4. Why does `build_db.py` drop and rebuild every table from scratch instead of
upserting?**
"Idempotent" here just needs re-running `make db-sample`/`make db` to produce the same
result, not fast incremental updates. At this corpus's scale (thousands of cases, not
millions), a full rebuild is cheap enough and trivially correct — no stale-row or
partial-update bugs to reason about. It would need to change if the full 2010-2025 build
became too slow to iterate on.

**5. Why SQLite with FTS5 instead of Postgres, given you know Postgres from your job?**
One file, no server process, free to host alongside the HF dataset, and FTS5's BM25 +
trigram tokenizer cover everything the resolver (M3) and support judge's retrieval (M5)
need without standing up infrastructure for what's currently a single-writer, thousands-
of-rows corpus. I recorded in DECISIONS.md that this would move to Postgres + `pg_trgm` +
`pgvector` at real scale — the choice is about matching infra to the actual problem size,
not avoiding Postgres.
