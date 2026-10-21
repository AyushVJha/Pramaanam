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
