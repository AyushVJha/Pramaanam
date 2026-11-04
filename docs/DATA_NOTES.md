# DATA_NOTES.md — M0 data inspection findings

Source: `indian-supreme-court-judgments` public S3 bucket (CC-BY-4.0). Inspected:
`metadata/parquet/year={2022,2023,2024}/metadata.parquet` (2655 rows total) and 20 random
PDFs sampled from `data/tar/year=2023/english/english.tar` (854 PDFs).

Reproduce with: `uv run python scripts/inspect_metadata.py` and
`uv run python scripts/inspect_pdfs.py` (after `make data-sample`).

## 1. What `citation` contains

**For 2022–2024, `citation` is never empty, and is 100% the official SCR (Supreme Court
Reports) format**, e.g. `[2023] 16 S.C.R. 872`. Across all 2655 rows, zero contain `SCC` or
`AIR` substrings — **no SCC or AIR (commercial-reporter) citations appear anywhere in this
metadata.**

```
CITATION FORMAT FREQUENCY (regex classification, all years combined)
  scr              2655  (100.0%)
```

This matches the SPEC.md §3.2 "design consequence" warning exactly: SCC and AIR are
commercial reporters and are **not** in the open metadata. The resolver's exact-citation path
can match SCR and neutral (INSC) citations only; SCC/AIR citations in a draft will have to
fall back to party-name + year fuzzy matching (M3), and that fallback rate needs to be
measured once the resolver exists. This limitation — not every citation format is
exact-matchable — goes in the README, not hidden.

## 2. What `nc_display` and `case_id` contain

`nc_display` holds the neutral citation with no internal spaces, e.g. `2023INSC1043`.
`case_id` holds the same neutral citation *with* spaces, e.g. `2023 INSC 1043` — it is **not**
an opaque row identifier despite the name. Checked across all 2655 rows:
`case_id.replace(' ', '') == nc_display` with **zero mismatches**.

`nc_display`/`case_id` are empty together in **4.7% of 2024 rows** (37/782) and **0% of
2022–2023 rows** — these are real judgments (with a valid SCR `citation`) that apparently
hadn't yet been assigned/scraped a neutral citation number as of the scrape date
(`scraped_at`). **Design consequence:** `case_id` cannot be used as the corpus's stable
primary key (it can be empty and isn't guaranteed unique by name). `cnr` and `path` are both
**100% non-empty and 100% unique** across all 2655 rows and are the better candidates for the
`cases` primary key in M1.

## 3. How party names are written (`title`, `petitioner`, `respondent`)

`title` is `"{petitioner} versus {respondent}"` (or similar); `petitioner`/`respondent` are
already split out as separate columns. Measured frequency of normalisation-relevant patterns
in `title`, across all 2655 rows:

| Pattern | Example | Frequency |
|---|---|---|
| `& Ors.` / `AND ORS` | `RAM LAL v. STATE OF RAJASTHAN & ORS.` | 43.2% |
| `& Anr.` / `AND ANR` | `ACHIN GUPTA v. STATE OF HARYANA & ANR.` | 25.8% |
| `M/s` / `M/S` | `M/S INDIAN OIL CORPORATION LIMITED v. ...` | 9.8% |
| `ETC.` | `... ETC. ETC.` | 4.2% |
| `(D)` / `DECEASED` | `HAR NARAYAN TEWARI (D) THR. LRS.` | 2.7% |
| `THR./THROUGH LRS` | `... THROUGH LRS.` | 3.2% |
| `IN RE:` | `IN RE: T.N. GODAVARMAN THIRUMULPAD` | 1.0% |

**Design consequence for party-name normalisation (M2/M3):** stripping `& Ors.`/`& Anr.`/
`AND ORS`/`AND ANR`/`ETC.`/`(D)`/`THR. LRS`/`M/s` covers the large majority of variation seen
here; `IN RE:` cases need special handling since there's no real respondent party. Case
spacing/punctuation is inconsistent (e.g. `"versus "` with trailing spaces, `AND` vs `&`), so
normalisation must be case-insensitive and whitespace-collapsing, not literal string matching.

## 4. PDF text extraction (20 random 2023 PDFs, PyMuPDF)

**20/20 (100%) had cleanly extractable text** — no scanned-image-only PDFs in this sample.
Page counts ranged from 6 to 316; char counts from ~12,500 to ~757,000.

**Paragraphs are numbered** with a `"<N>. "` marker at the start of a line (regex
`^\s*(\d{1,3})\.\s`) — found in all 20 sampled PDFs, e.g. judgment
`2023_15_848_865_EN.pdf` has 34 such markers. This loose regex has a known false-positive
risk: it also matched standalone page/footnote numbers in 2 of 20 PDFs (e.g. `'142'`,
`'366'` appearing as spurious "paragraph" numbers) — the M1 paragraph splitter needs a
stricter rule (e.g. require the number to restart near 1 and increase monotonically, or
anchor on page layout) rather than this bare regex.

No PDFs used `[N]`-bracketed paragraph markers (0/20 matches for that pattern).

**Two visually distinct layouts observed** in the sample:
1. **Short-headnote layout**: starts with `CASE DETAILS`, petitioner, `v.`, respondent, bench
   and date, then a `HEADNOTES` section (`"Issue for consideration: ..."` prose summary)
   *before* the numbered judgment text begins. Example:
   `[2023] 15 S.C.R. 848 : 2023 INSC 1073 ... CASE DETAILS ... HEADNOTES Issue for
   consideration: ...`
2. **Margin-letter layout**: pages carry a vertical `A B C D E F G H` sequence of single
   letters in the left margin (visible as `'A \n B \n C \n D \n E \n F \n G \n H \n'` at the
   top of extracted text) before the citation/party header. These are the printed SCR
   margin-line markers used for pincite referencing within the official report, independent of
   the numbered-paragraph markers above.

**Design consequence (M1):** the headnote block (`HEADNOTES` / `"Issue for consideration"`)
is editorial summary, not part of the court's reasoning, and must be excluded or clearly
separated from the numbered paragraphs that `checks/quotes.py` and `checks/support.py` will
search — otherwise a quote from the headnote could be wrongly confirmed as judgment text. The
margin `A`–`H` letters are page-layout noise for our purposes (not citation-relevant) and
should be stripped during paragraph splitting.

## 6. M1 — corpus DB build (year=2023, `make db-sample`)

Reproduce with: `uv run python -m pramaan.data.build_db` (after `make data-sample`).

```
years:                        [2023]
cases:                        856
paragraphs:                   17002
% cases with zero paragraphs: 0.2%
% cases with neutral citation: 100.0%
```

**2/856 cases (0.2%) have zero paragraphs** — not an extraction bug: both case's PDF
filenames (derived from metadata's `path` column) are genuinely absent from
`english.tar`. The tar's own `english.index.json` reports `file_count: 854`, exactly
`856 - 2`. This is a real, small gap in the source archive relative to its metadata, not
something this codebase can fix — it's recorded here rather than silently producing an
empty-paragraph case with no explanation.

**Spot-check of 20 random judgments (paragraph numbers + first lines) found 3/20 (15%)
where paragraph numbering doesn't start at 1** — all 3 are judgments that quote another
case's own numbered paragraphs at length (e.g. one quotes the *De Beers Consolidated
Mines* tax-residency precedent's paragraph 8). The splitter's "longest monotonic run"
heuristic (see DECISIONS.md) picks up the quoted material's numbering instead of the real
judgment's shorter true opening run, dropping the judgment's first few paragraphs. This is
a measured, documented limitation — not hidden — see
`tests/test_paragraphs.py::test_quoted_material_with_own_numbering_is_a_known_limitation`
for a locked-in example.

## 7. M2 — citation extraction

`citations/patterns.py`/`extract.py`/`normalise.py` are built and unit-tested (44 tests,
`tests/test_patterns.py`) against real SCC/AIR/SCC-OnLine/SCR/neutral citation strings
pulled directly from judgment *body text* (not the `citation` metadata field, which M0
found has zero SCC/AIR — but judgments cite other cases in every format throughout their
own text; see DECISIONS.md).

**Precision/recall per format: not measured yet.** `scripts/label_extraction.py` (the
hand-marking CLI) and `scripts/eval_extraction.py` (the report) are built and ready, but
per PROMPTS.md the actual gold-label marking (~1 hour, 10 real judgments) must be done by
a human, never the AI. This section will be filled in with real precision/recall numbers
once that's done — not before.

**Found and fixed while walking through the very first real hand-marking example:**
PyMuPDF's plain-text extraction interleaves two kinds of SCR print furniture into the body
text with no structural marker — a running page-top header ("SUPREME COURT REPORTS\n[YYYY]
V S.C.R.") and a running footer that repeats the case's *own* title ("X v. Y"). The footer
was making `citations/extract.py` mistake a judgment's own header for a citation to a
*different* case. Fixed in `pdf_text.py` (generic header strip + fuzzy-matched footer strip
against the case's own known petitioner/respondent — see DECISIONS.md for why a second,
differently-bounded regex was needed). Re-scanning 150 judgments after the fix found **0
remaining own-title leaks**, down from a real, previously-uncounted contributor to
CASE_NAME false positives. `make db-sample`'s paragraph count shifted from 17,002 to
16,960 as a direct, expected consequence (the stripped footer text occasionally sat inside
what had been counted as paragraph content).

## 8. Not yet answered (out of M0 scope, flagged for later)

- Only years 2022–2024 were inspected, per the approved M0 plan. Pre-2023 judgments (before
  the Supreme Court's neutral-citation scheme, per Bar & Bench) may rely on SCC/AIR citations
  that genuinely appear in `citation` for older years — this needs re-checking once the year
  range expands in M1, rather than assuming the 2022–2024 pattern holds further back.
- Row counts per year: 2022 = 1017, 2023 = 856, 2024 = 782.

## 9. Full-corpus coverage (1950-2026), measured 2 Nov 2026

Source: `uv run python scripts/measure_coverage.py` on the full DB (output saved in `logs/coverage_full.txt`).

**Corpus.** 38,397 distinct cases and 478,691 paragraphs. Another 5,181 cases appear in two year folders and are kept once (see DECISIONS.md). 5 cases have no PDF. Cases per decade: 1950s 899, 1960s 3,010, 1970s 3,026, 1980s 2,865, 1990s 6,497, 2000s 9,082, 2010s 7,942, 2020s 5,076.

**Citations found inside judgment bodies, and how many resolve by exact lookup** (the cited case is not the citing case):

| Format | Found | Resolved | Rate |
| --- | --- | --- | --- |
| SCR | 32,076 | 22,001 | 68.6% |
| Neutral (INSC) | 760 | 547 | 72.0% |
| SCC | 56,734 | not resolvable | n/a |
| AIR | 14,469 | not resolvable | n/a |
| SCC OnLine | 1,433 | not resolvable | n/a |

SCC, AIR and SCC OnLine numbers are not in the dataset, so they cannot be looked up directly. Of 27,601 paragraphs that cite SCC or AIR, only 2,809 also contain a resolvable SCR or INSC citation in the same paragraph. That is about 10%, so a same-paragraph crosswalk is not enough. Most SCC/AIR citations will need the fuzzy party-name plus year path.

**SCR resolution by cited decade.** Cited 1960s to 1980s: 88 to 90%. Cited 1990s to 2020s: 60 to 67%. Cited 1950s: 17.7% (1,352 of 7,634). Citations to cases before 1950 never resolve (0 of 39). The 1950s corpus has only 899 cases, far fewer than the later decades. I have not checked why, so I do not know if the dataset is incomplete for that decade or something else is going on. Cited neutral 2020s: 56% (269 of 480), cause also not checked.

**Not measured:** whether the matched citation strings are all real citations, and whether each resolved match points to the right case. Both need hand-labelled data.

## 10. M2 extraction labels: who labelled what

PROMPTS.md says the M2 gold data must be hand-marked by Ayush. He labelled 3 of the 26 remaining items on the labelling page, then asked Claude to do the rest. So the labels are split by file and by a `labeller` field:

- `bench/data/extraction_gold.jsonl` has Ayush's rows, 4 in total. The first came from the terminal tool, the other 3 from the page.
- `bench/data/extraction_gold_claude.jsonl` has 23 rows labelled by Claude (`claude-sonnet-5-5`). They are not human gold and must be reported as Claude-labelled.

Run `uv run python scripts/eval_extraction.py` for the human rows only. Pass both files to pool them. Pooled results (27 rows, 20 candidates) are a smoke test, not a result to quote: CASE_NAME is 5 candidates and 2 correct, SCC is 11 candidates, SCR 2, AIR 1, NEUTRAL 1. The sample is far smaller than the 100 citations PROMPTS.md asked for.

Judgment calls Claude made that Ayush may overrule: a citation in the judgment's own header counts as correct (it is a real citation string, just a self-citation). A High Court "SCC OnLine Bom" citation counts as not missed, since the patterns cover the Supreme Court only. A case-name span that starts with "In" or "Lord Davey in" counts as incorrect, which matches Ayush's own answer on the first such item.

## 11. M3 resolver results, measured 4 Nov 2026

Source: `logs/m3_results.txt`, produced by `bench/tune_resolve.py` and `bench/eval_resolve.py`. Threshold 0.85, chosen on dev only. The test split was first run once the threshold was fixed. It was re-run afterwards only to confirm the results did not change after a determinism fix (word order was random between runs).

| Split | Items | Correct | Wrong case | Missed | Ambiguous | Hidden-case lookalike match |
| --- | --- | --- | --- | --- | --- | --- |
| Dev | 246 | 85.0% | 1.2% | 13.8% | 0% | 8.9% |
| Test | 667 | 85.0% | 0.7% | 13.8% | 0.4% | 7.2% |

"Hidden-case lookalike match" is leave-one-out: the true case is removed from the corpus, so the right answer is no match, and the figure is how often a different case was returned anyway.

**What this covers.** Only the fuzzy step, on SCC (about 70% of items), AIR (about 29%) and SCC OnLine (about 2%) citations that carry a case name. The exact step is correct by construction wherever the number is in the corpus.

**How often the fuzzy step is needed.** Of 105,472 structured citations found in judgment bodies (section 9), 22,548 (21.4%) resolve by exact lookup. 72,636 (68.9%) are SCC, AIR or SCC OnLine and can only go through the fuzzy step. Another 9.8% are SCR or neutral numbers that do not match any case. So up to 78.6% of citations in real judgments need the fuzzy step.

**Not measured:**
- Why 13.8% are missed. On dev, I saw name-extraction noise (leading words like "It was in", line breaks, names cut at "Ltd.") and abbreviated names ("LIC", "CWT"). I have not counted them on test and did not tune on it.
- Accuracy when the draft gives no case name. Such citations cannot be resolved at all.
- Accuracy on hallucinated or garbled names. The benchmark uses names as real judgments write them.
- The identity check's threshold (0.7). It is a starting value with no benchmark yet.

**Known benchmark weaknesses.** Truth depends on the parallel SCR or neutral number in the judgment being right. A mistyped number that points to a different real case would give a wrong answer key. Items were capped at 3 per cited case, so famous cases do not dominate. The builder was revised after I read dev errors, and never after looking at test errors, except that I read the 8 unmatched-anchor test items to see whether the label was sound.

## 12. M4 quote and paragraph check results, measured 4 Nov 2026

Source: `logs/m4_results.txt` from `bench/tune_quotes.py` and `bench/eval_quotes.py`, and `logs/m4_real_quotes.txt` from `bench/measure_real_quotes.py`. Threshold 85, chosen on dev only. Test was run once with it fixed.

**Synthetic benchmark (truth by construction).** Test split, 1,991 items from 275 judgments:

| Kind | Items | Right status |
| --- | --- | --- |
| Real quote | 275 | 100.0% verbatim |
| One word changed | 274 | 100.0% near match |
| Negation added or removed | 226 | 99.6% near match, flag raised on 225 |
| Number changed | 117 | 100.0% near match, flag raised on 117 |
| Spliced from distant paragraphs | 274 | 98.9% not found |
| Sentence from another judgment | 275 | 100.0% not found |

Altered quotes reported verbatim: 2 of 1,166. One is a benchmark flaw: the altered text happens to exist elsewhere in the same judgment. The other is the known weakness in DECISIONS.md: short pieces after "...." are ignored. The paragraph check was right on 275 of 275 correct pinpoints, 275 of 275 off-by-one pinpoints and 272 of 275 far-off pinpoints. Dev results are within a point.

**What this does not show.** The benchmark is easy by construction, so near-perfect scores say the logic works, not that real quotes will pass. Real hallucinated quotes come in M6.

**Real quotes between judgments (not a labelled accuracy).** Of 580 quotes ending just before an exactly resolvable SCR or neutral citation, the checker found 3.4% word for word and 15.2% as near matches (85 to 99% of words agree). 76.2% had no similar passage in the cited case. I read examples and cannot turn this into a misquote rate. Two things blur it: the nearest citation is not always the source of a quote, and cited cases from the 1950s to 1980s (90% of the pairs) carry OCR noise, so even an exact quotation rarely matches word for word. Only 19 cited cases were from the 2020s, too few to read anything from them (6 verbatim, 6 near, 7 not found).

**What I take from it.** For old cases, a near match with a few changed words is the normal outcome of an honest quote, so near match must not be reported as a misquote. M7 has to decide how to map statuses: my suggestion is that a near match with no negation or number flag counts as supported, and one with a flag goes to review.

**Not measured:** how often a real quote from a judgment's headnote is wrongly reported as not found (headnotes are dropped when paragraphs are built); the effect of footnote text mixed into body paragraphs; the quote check on text from the 2000s onward at a useful sample size.


## 13. SCC / AIR alias table (resolver extension)

The dataset has no SCC or AIR numbers (section 9), but judgments print them beside numbers it does have ("(2001) 2 SCC 386 : [2001] 1 SCR 1"). `src/pramaan/data/build_aliases.py` mines these pairs into `citation_aliases`, one row per piece of evidence plus the judgment that printed it.

Rules: the group must hold exactly one SCR or neutral number that resolves to exactly one case; the SCC/AIR number must be within 2 years of it; a judgment citing itself is skipped. SCC OnLine is not mapped.

Measured with `scripts/explore_parallel_citations.py` (log `logs/explore_parallel.txt`), whole corpus:
- 2,496 clean groups gave 2,506 evidence rows and 1,839 distinct SCC/AIR numbers.
- Of the 390 numbers seen in two or more judgments, 385 (98.7%) agree on one case. 5 numbers have conflicting targets.
- Held-out: map built from 70% of citing judgments (hash group), scored on the other 30%. 756 SCC/AIR citations had a known true case. The map answered 201 (26.6%): 199 right, 2 wrong (99.0% precision).
- Caveat: the held-out truth is the same kind of printed pair as the map, so this shows agreement between independent judgments, not independent proof. The 26.6% is for citations that have a printed parallel number; coverage on real drafts is not measured.

Resolver effect, dev split only, with each item's own citing judgment left out of the evidence (`bench/eval_resolve.py --split dev`, logs `m3_dev_before_alias.txt` and `m3_dev_after_alias.txt`):
- correct: 209/246 (85.0%) to 223/246 (90.7%); wrong case: 3 to 1.
- Hidden-case lookalike match (leave-one-out): 22/246 (8.9%) before and after.

Test split, run once with the alias step (threshold 0.85 unchanged, nothing tuned; log `logs/m3_test_after_alias.txt`):
- correct: 567/667 (85.0%) to 600/667 (90.0%); wrong case: 5 (0.7%) to 6 (0.9%).
- Hidden-case lookalike match (leave-one-out): 48/667 (7.2%) to 49/667 (7.3%).
- Test is consistent with dev (90.7%). The gain is real but modest, and wrong-case answers and lookalike matches did not go down: one more of each. Per format: AIR 151 to 167 correct, SCC 404 to 421, SCC OnLine unchanged at 12 (the alias step does not cover it).
- The test split has now been run twice in total for the resolver: once for the M3 result, once for this step. The step was designed and checked on dev only.

## 14. Is the text usable? Scans, OCR and tables (measured 4 Nov 2026)

We run no OCR of our own: PyMuPDF reads the text layer already inside each PDF. The older judgments are scans, so the question is whether that layer exists and how clean it is. Scripts: `scripts/measure_text_coverage.py` (log `logs/text_coverage.txt`) and `scripts/measure_text_quality.py` (log `logs/text_quality.txt`). Samples, not the whole corpus.

**Is there text?** In the 8 sample years (1955 to 2023, 177 to 917 PDFs each), 0.0% of PDFs were mostly empty (more than half the pages under 30 characters) and the median empty-page share was 0.0%. Every decade has 0.0% of cases with no paragraph rows (a few cases per decade are below the rounding). So the scans carry an embedded text layer (presumably from the source's own OCR). Not checked: every year, and whether a missing PDF or an image-only page hides somewhere in the other years.

**How clean?** Unknown-word rate (share of 4+ letter tokens absent from a vocabulary built from 300 clean 2020 to 2025 judgments; names and old spellings also count, so read it as a trend): 1950s 12.2%, 1960s 12.7%, 1970s 13.9%, 1980s 11.3%, 1990s 9.2%, 2000s 7.8%, 2010s 6.8%, 2020s 6.1%. Old text is noisier by roughly two times, not broken. This is not an OCR error rate: it was not checked against a hand-typed reference.

**How much of the text reaches the database?** Median share of raw page text kept as paragraphs: 99% for the 1955 to 2005 samples, 67% for 2015 and 75% for 2023 (headnotes and front matter are dropped on purpose).

**Fewer paragraphs in older judgments.** Median paragraphs per case: 1950s 12, 1960s 10, 1970s 7, 1980s 7, 1990s 5, 2000s 10, 2010s 13, 2020s 15. The 1990s figure is low. Not yet explained: either many of those judgments are short or not numbered, or the splitter merges text. A paragraph reference such as "para 23" is only checkable where the judgment's numbering was recovered.

**Tables.** Not handled. Table cells arrive as flattened lines inside whatever paragraph surrounds them, so numbers in tables are unreliable for quote checks. Not measured: how many judgments contain tables that matter.

## 15. Source audit: is the corpus complete? (measured 4 Nov 2026)

Script: `scripts/audit_source.py` (writes `logs/audit_source.txt` and `logs/audit_gaps.csv`; both
gitignored, so the numbers below are the record). Re-run it to reproduce.

**What was checked**
- 38,392 of 38,397 file names parse as `year_volume_start_end`. The start page equals the printed
  SCR citation page in 5,000 of 5,000 cases checked.
- 488 volumes. Page ranges tile the volumes almost completely: 31 gaps of more than 2 pages,
  holding 1,019 pages. Share of pages inside big gaps is 0.0 to 0.1% per decade, except the 2020s
  at 0.6% (largest: 2023 vol 10, pages 159-289; 2026 vol 8, pages 326-453).
- 22 duplicate page ranges and 1 inverted range. Not yet investigated.

**Neutral citation numbers (INSC), 2014 onward.** Before 2014 the numbers are contiguous because
the dataset assigned them itself, so that range says nothing. From 2014 the numbers have holes:

| year | highest | present | missing |
|------|---------|---------|---------|
| 2014 | 1046 | 763 | 27% |
| 2016 | 1215 | 564 | 54% |
| 2019 | 1415 | 1039 | 27% |
| 2020 | 716 | 563 | 21% |
| 2023 | 1093 | 851 | 22% |
| 2025 | 1425 | 893 | 37% |
| 2026 | 981 | 235 | 76% (year in progress) |

One outlier: "2024 INSC 4354" (KOLKATA MUNICIPAL CORPORATION v. BIMAL KUMAR SHAH). The next
highest 2024 number is 1100, so 4354 is probably a typo in the source. Left as is, flagged.

**What this suggests (NOT verified)**
The corpus looks like the Supreme Court Reports volumes, almost fully present, and not every
judgment the Court ever delivered. Recent unreported judgments would then be largely absent. I
have not checked this against an independent list, so it is a hypothesis.

**Consequence for the product, whatever the cause**
`NOT_FOUND_IN_CORPUS` must never be read as "fake". For 2014 onward, 20 to 55% of neutral numbers
are simply not in this dataset. The report already says so; the corpus manifest (later step) must
state coverage per year so a user can see it.

**Not done yet:** classify each PDF as born-digital or scanned; investigate the duplicate and
inverted ranges.
