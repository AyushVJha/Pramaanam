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

## M2 — Citation extraction

**1. M0 found zero SCC/AIR citations in our metadata. How did you get real SCC/AIR test
strings for M2 without inventing them?**
I looked in the right place: M0's "zero SCC/AIR" finding was about the `citation` metadata
field, which only records a judgment's citation of *itself*. The judgment's own *body
text* cites other precedents in every format — a corpus-wide scan found 3,445 real SCC
strings, 458 AIR strings, and 163 SCC OnLine strings sitting in paragraph text (e.g. "AIR
2005 SC 626" inside a sentence quoting *Bhanu Kumar Jain v. Archana Kumar*). All of
`test_patterns.py`'s positives for those three formats come from that scan, not from
public-knowledge landmark cases or anything invented.

**2. Your case-name regex initially matched a party name AND ran straight into the next
citation's digits. What was wrong, and how did you know?**
Appendix A's suggested character class for the name parts was `[\w.&,'\- ]`, which
includes digits and commas — so on real text like "Archana Kumar, AIR 2005 SC 626" the
match didn't stop at the comma, it kept consuming through "AIR 2005 SC 626" too, because
digits are `\w`. I caught it by actually running extraction against real corpus text
instead of trusting the pattern because it came from the spec — the fix excludes digits
and commas from that character class.

**3. The case-name format still has known false positives. What are they, and why ship
it anyway?**
Running the extractor across 15 real paragraphs surfaced two recurring patterns: (a) a
judgment's own case-name header getting matched as if it cited a *different* case, and
(b) a short run of capitalized words right before "v." occasionally passing the
capitalization-ratio filter even when it's actually a sentence fragment (e.g. "...General
sought to refer to Rameshwar & Ors. v. State of Haryana"). Both are measured, named
limitations, not swept under the rug — and this exact format is the one SPEC.md itself
flags as needing an LLM fallback for real precision, which isn't built until M5+. Shipping
a heuristic-only version now and measuring its actual precision via hand-marking (rather
than either blocking on M5 or guessing at a number) is the honest middle path.

**4. Why didn't you just have the AI generate the extraction gold labels — wouldn't that
be faster?**
Because PROMPTS.md is explicit that this is the one thing I must never do: "This is your
gold data — never let the AI label it for you." If I labeled my own extractor's output,
any error pattern my code is blind to would never get caught — the whole point of a human
in the loop is to catch exactly the mistakes the system that produced the candidates can't
see in itself. I built the CLI, picked a representative (not cherry-picked) sample of 10
judgments by candidate count, and the actual correct/incorrect judgment is entirely yours.

**5. Your "recall" measurement only catches misses containing "SCC"/"AIR"/"INSC"/"SCR" —
isn't that going to overstate recall?**
Yes, and I say so directly rather than letting the number imply more than it measures:
it's a lower bound on recall for the 5 structured formats, and explicitly "not measured"
for case names, where there's no reliable token to scan for. A full re-read of 10
judgments for exhaustive recall would blow well past PROMPTS.md's ~1 hour estimate for
this task; the token-scan is a deliberate, stated trade-off between thoroughness and the
time budget — not an attempt to make the number look better than it is.

**6. The user caught a false positive on the very first candidate they looked at, before
any formal labeling happened. What was it, and what does it say about your process?**
A judgment's own title repeats as a running header/footer throughout the printed SCR
volume (print convention), and PyMuPDF's plain-text extraction interleaves that into the
body text with no structural marker separating it from real content — so the extractor
mistook the judgment's own header for a citation to a *different* case. The useful signal
wasn't the bug itself (regex-based extraction on real legal text was always going to have
edge cases) — it's that a single real example, actually read end-to-end with the user
before any bulk labeling started, surfaced a systematic root cause in under five minutes
that could have otherwise consumed a meaningful fraction of the 100 hand-marked labels as
one-off "incorrect" marks. I fixed the root cause in `pdf_text.py` rather than treating it
as 15+ individual labeling annoyances, and measured the fix's actual impact (0 remaining
own-title leaks across 150 re-scanned judgments) instead of assuming it worked.

**7. Why does the footer-stripping fix need a *different*, unbounded regex instead of
reusing `citations.patterns.CASE_NAME`?**
Because the two use cases have different risk profiles. `CASE_NAME` is capped at 8 words
per side specifically to stop it from swallowing a whole preceding sentence when scanning
arbitrary draft text for *any* case name (SPEC.md's own "high recall, low precision"
format). The footer-stripper doesn't have that risk the same way — it only deletes a match
if it *also* fuzzy-matches the case's own known petitioner/respondent names above an 80%
threshold, so an unbounded match is safe there and necessary: this case's own corporate
party name is 10 words long ("GODREJ AND BOYCE MANUFACTURING COMPANY LIMITED THROUGH ITS
CONSTITUTED ATTORNEY"), and the 8-word cap was truncating it, leaving a dangling fragment
behind. Same literal problem (matching "X v. Y"), different constraints, so a second,
purpose-built pattern was the right call rather than forcing one regex to serve both.
