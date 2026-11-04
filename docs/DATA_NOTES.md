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

**Source README check (4 Nov 2026).** The dataset README (github.com/vanga/indian-supreme-court-judgments)
says the repo holds "the code to download judgments from" `scr.sci.gov.in`, covers "1950 to
Present", and has "~35K judgments in english". It does NOT say: how the PDFs or their text were
produced (OCR or not), whether it covers all judgments or only reported ones, known gaps, or an
update schedule. The domain name (SCR) fits the hypothesis that this is the Supreme Court
Reports portal, i.e. reported judgments, but that is an inference from a name, not a stated fact.
Our DB holds 38,397 cases against the README's "~35K" (approximate figure, difference not explained).
Next: ask the maintainer, or check the portal's own description, before relying on the hypothesis.

**Duplicate ranges, inverted range and cases without a PDF (checked 4 Nov 2026).**
- **The 22 "duplicate" page ranges are not duplicates.** Each pair is two different cases, one with
  file name `1992_2_1_12_EN.pdf` and one with `S_1992_2_1_12_EN.pdf`. The `S_` files are the SCR
  *Supplement* series, which restarts page numbers inside the same year and volume number.
  The audit grouped both series under one key, so its tiling numbers mix two series. It needs
  re-running with the series kept apart (not done yet).
- **7,641 cases (about 20% of the corpus) are Supplement cases.** Their metadata citation reads
  e.g. `[1992] SUPP. 2 S.C.R. 1`. `parse_scr` returns None for that form (the regex accepts
  `Supp. (2)` with brackets, not `SUPP. 2`), so these cases have NO SCR row in `case_citations`,
  only their INSC number. A user citing `[1992] Supp. (2) SCR 1` therefore cannot be matched to them.
- **Wrong-match risk, found by reading the code, not yet measured:** `parse_scr` accepts
  `[1992] Supp. (2) SCR 1` but drops the Supp marker and the volume, giving year 1992, volume None,
  page 1. The resolver then matches any regular-series case on page 1 of 1992, which can be a
  different case from the one cited. Not yet tested against real data.
- **1 inverted range:** `1972_3_973_972_EN.pdf` (D. N. Bhattacharjee v. State of West Bengal),
  start 973, end 972: a typo in the file name. Harmless, not corrected.
- **5 cases have no PDF at all** (path is empty): 1996 (1), 1999 (2), 2023 (2). They have metadata
  only, so they can be found but not checked.

**Supplement fix and its measured effect (4 Nov 2026, dev split only).** `parse_scr` now gives
Supplement citations the reporter `SCR-SUPP` (DECISIONS.md). After rebuilding the database:
- `case_citations` holds SCR 30,755 rows and SCR-SUPP 7,642 rows (before: SCR 30,755, none for
  Supplement). Cases 38,397 unchanged. Alias evidence rows 2,506 to 2,800, because Supplement
  parallel citations now count as anchors.
- Resolver on dev: 222/246 correct (90.2%), 2 wrong-case. Before the fix: 223/246 (90.7%), 1
  wrong-case. That is one item either way, within noise on 246 items. One new wrong answer is
  alias-based ("Basheer v. State of Kerala", (2004) 3 SCC 609, answered with a 2003 case at
  confidence 0.99). It was not tuned away and not yet investigated. The dev benchmark has no
  Supplement-form items, so it cannot show the gain; the gain is that those 7,642 cases can now
  be found by their SCR citation at all, which is not measured here.
- Test split not re-run: it is spent once, at the end.
- Unexplained: paragraphs went 478,691 to 478,709 (+18) in the rebuild. The text layer did not
  change, so this probably predates this fix (an earlier code change not rebuilt into the old
  database). Not investigated.

**The one new wrong alias answer, traced (dev only).** "Basheer v. State of Kerala", (2004) 3 SCC 609.
The held-out judgment says it is N.P. Basheer ([2004] 2 SCR 224). Another judgment (In Re: Section
6A of the Citizenship Act, 2024) prints, in a footnote, "[2003] Supp. 1 SCR 580 : (2004) 3 SCC 609"
for A. Mohammed Basheer, a different 2003 case. With the first judgment held out, that footnote was
the only evidence, so the alias step answered with the 2003 case. Before the Supplement fix
this footnote was not parsed as an anchor, which is why the error is new. Either the footnote or
the first judgment prints a wrong parallel citation: the source itself is inconsistent, and I have
not checked which one is right.
Alias answers on dev by number of independent citing judgments backing the answer: 1 judgment:
49 right, 1 wrong; 2 judgments: 15 right; 3 or more: 22 right. Tiny numbers, so no threshold or
confidence was changed. What this does suggest for the verdict design: an alias-only answer backed
by one judgment must not be reported as proof; it needs the case name and year to agree as well.
Reproduce: `uv run python scripts/alias_witness_dev.py`.

## 16. First look at text engines: embedded layer vs Tesseract (4 Nov 2026) - EXPLORATORY

**How measured.** `bench/eval_ocr_engines.py`, labels in `bench/labels/claude_excerpts.json`. For
10 pages (one per roughly 4th page of the 40-page small sample, 1955 to 2024) Claude transcribed one
block of body text from the page image BEFORE looking at any engine output. These are NOT
human-verified labels (the human check, `viewer_small`, is still open) and Claude can misread
print. Score = character error rate of the best-matching stretch of the engine's page text, so
margin letters and running heads do not count; line-end hyphens, quote styles and whitespace are
normalised. Nothing was tuned on these pages.

**Result (CER, lower is better).**

| | embedded layer | Tesseract psm 3 | psm 4 | psm 6 |
|---|---|---|---|---|
| median | 0.016 | 0.002 | 0.004 | 0.020 |
| mean | 0.030 | 0.019 | 0.029 | 0.041 |
| worst page | 0.169 | 0.171 | 0.161 | 0.154 |

**What it says, and does not say.**
- On most of these pages the embedded layer is already close (8 of 10 pages under 3%), and
  Tesseract with automatic layout (psm 3) is about as good or better (median 0.2%).
- The embedded layer is not always that good: the page that prompted this work
  (1955_2_919_924 p1, "settll", "wit~1", words split one per line) is not in the 10, so n=10 may
  understate its errors. That page was seen with the engine text, so it was not used as a blind label.
- **The worst page (1961_1_113_117 p1, about 16% for every engine) is a layout problem, not a
  character problem:** the side notes (the case name printed in the margin) are inserted into the
  middle of a body sentence by both the embedded layer and Tesseract. A quote spanning that spot
  would not be found. The same happens with psm 4 and 6 on 1955_1_872_876 p3 (10 to 12%), where
  psm 3 is clean. Character accuracy alone will not catch this; reading order and side-note
  handling need their own measurement.
- Not measured: tables, footnotes, other engines (Docling, Marker, PaddleOCR, a vision model),
  more than 10 pages, human-verified labels.

**Docling added (same 10 pages, same labels, still exploratory).** Docling 2.145.0 run from the
Python environment of another project on this Mac (`/Users/ayush/factget/.venv`; Docling is NOT
installed in Pramaan and no code from that project is used). Script: `bench/docling_pages.py`
(`default` and `ocr` modes), then `bench/eval_ocr_engines.py` scores everything.

| CER | embedded | Tesseract psm 3 | Docling default | Docling + full-page Tesseract OCR |
|---|---|---|---|---|
| median | 0.016 | 0.002 | 0.006 | 0.005 |
| mean | 0.030 | 0.019 | 0.055 | **0.005** |
| worst page | 0.169 | 0.171 | 0.294 | **0.010** |

- Docling's layout model on top of the embedded text ("default") is no better, and worse on 3
  pages (worst 29%): it keeps the embedded layer's character errors and reorders blocks.
- Docling's layout model on top of a fresh full-page Tesseract read ("ocr") is the best here on
  every summary line, including the page every other engine failed (1961 p1: 0.8%, because the
  margin case name no longer cuts into the sentence).
- Speed on this Mac: median 2.5 to 3.8 s per page, max 9.2 s (model load not counted).
- It is not clean. On the same 1961 page: a stray "High" broke the sentence end ("and in the Court"),
  the running head and the side notes (year, party names, judge) were dropped or scattered, and two
  title lines came out in the wrong order ("TRIVEDI" before "SHRI BALWANTRAI CHIMANLAL"). Dropping
  side notes helps quoting but loses the case-name block. The excerpt metric cannot see these.
- Limits: 10 pages, labels transcribed by Claude, not by a human; excerpts are body paragraphs, so
  headings, tables and footnotes are not scored. These numbers say "worth testing properly", not "adopt".

**All 40 pages of the small sample (same fixed rule, no pages chosen, still exploratory).** The
other 30 pages were transcribed by Claude with the same rule and BEFORE any engine output was
looked at (one page, 1955_2_919_924 p1, had been seen with its engine text, so it is shown but left
out of the summary: 39 blind pages). Labels: `bench/labels/claude_excerpts.json` (40 items). Still
NOT human-verified. Reproduce: run `bench/docling_pages.py default` and `... ocr` with a Python that
has Docling, then `uv run python bench/eval_ocr_engines.py` (about 3 minutes; the scorer uses
numpy, which pandas already brings in).

| 39 blind pages, CER | embedded | Tesseract psm 3 | psm 4 | psm 6 | Docling default | Docling + OCR |
|---|---|---|---|---|---|---|
| mean | 0.021 | 0.011 | 0.017 | 0.031 | 0.043 | **0.006** |
| median | 0.010 | **0.003** | **0.003** | 0.013 | 0.006 | 0.006 |
| worst page | 0.169 | 0.171 | 0.161 | 0.154 | 0.423 | **0.021** |
| pages over 5% error | 3 | 2 | 4 | 6 | 8 | **0** |
| pages over 1% error | 20 | **6** | 7 | 26 | 15 | 10 |

- **Docling + full-page OCR has no bad page** (worst 2.1%) and the lowest mean; Tesseract with
  automatic layout has the lowest median and the fewest pages over 1%, but two pages near 10 to 17%
  (both pages with a margin side-note block cutting into the body text: 1961 p1, 1960 p29).
  So the two make different kinds of mistakes: Tesseract is slightly more exact on characters,
  Docling is safer on layout.
- **Docling's default mode (layout over the embedded text) is worse than the embedded text alone**
  on 8 pages (up to 42%): it reorders blocks and keeps the embedded layer's noise. Do not use it.
- **The embedded layer** has 3 bad pages and 20 pages over 1% error. It is usable, not safe.
- **Likely label noise:** 2024_6 p1 is 2.1% for every engine, which points at my transcription
  (quote or dash handling), not at the engines. The size of my own error is not measured, so
  differences below about 1 to 2 points should not be read as real.
- Speed on this Mac: Docling + OCR median 2.7 s per page (max 7.4); default 3.9 s (max 10.3).
- Not covered: tables, footnotes, headings and side notes (excerpts are body text only), scans
  worse than these, other engines (Marker, PaddleOCR, a vision model), human-verified labels.

## 17. Layout build throughput (measured 2026-11-05)

Docling + full-page Tesseract on this laptop (4 workers, run at low priority): 360 judgments / 7,900 pages of 2024 in about 110 minutes, 0 failures, 5.7 MB of blocks. That is about 1.2 pages/s. The whole corpus (682,658 pages) would take about 158 hours, so a whole-corpus layout build on this machine is not practical. Layout is therefore used as an on-demand second reading for judgments a draft actually cites (and for evaluation samples), not as the primary text of every judgment. Partial 2024 store kept (resumable). Build stopped by hand.

Profile of one 5-page judgment (laptop, 4 threads, docling timings): OCR 6.3 s, layout network 1.2 s, whole pipeline 6.6 s (stages overlap). OCR is Tesseract on CPU, so a GPU does not speed up the main cost.

Candidate machine (specs as reported by the owner of the account, no access granted): 2 x AMD EPYC 7763, 128 physical cores, 1 TB RAM, one A100 80 GB shared with other jobs. If one core matches one laptop worker (not measured) and scaling is linear (optimistic), 32 workers is about 20 h and 64 workers about 10 h for the whole corpus. Not run: needs the owner's approval; first step would be a 50-page timing test at lowest priority, CPU only. Selective OCR (OCR only pages whose embedded text looks bad) could cut this further, but needs a page-quality flag that has not been built or validated, so no saving is claimed.

## 18. End-to-end pipeline on the resolver benchmark, dev split (2026-11-05)

`bench/eval_pipeline.py --split dev` (no AI check; output in logs/pipeline_dev.txt). 246 items, each hiding the evidence printed by the citing judgment itself.

- VERIFIED 34, FALSE VERIFIED 0 (VERIFIED on a wrong case).
- 185 items got the right case but only NEEDS_REVIEW: 137 were found by name only (no alias evidence left once the citing judgment is hidden) and 50 had a single witness. 22 true cases came out NOT_FOUND_IN_CORPUS, 2 wrong cases were NEEDS_REVIEW (not asserted), 3 got NAME_MISMATCH.
- Caveat: hiding the citing judgment removes one witness from every alias, so this under-states how many a real draft would verify. The safety number (zero false VERIFIED) is the one this benchmark can support; the coverage number is a floor, not an estimate for real drafts.
- Dev only. Test split not run.

## 19. Neutral numbers shared by more than one judgment (2026-11-05)

96 (year, number) pairs of INSC citations are printed on 2 or more judgments (14 on 3 or more). Looking at the first rows: some are later orders in the same matter that print the earlier judgment's neutral number (e.g. three Sushil Ansal v. State orders of 2014-2015 all carry 2014 INSC 168); others are different cases (Bhule Ram v. Union of India and Raja Ram v. Union of India both 2014 INSC 222). We have not worked out which are source errors. The resolver returns NEEDS_REVIEW "matches more than one judgment" for these, which is the safe behaviour. Idea, not built: when the draft's own case name matches exactly one of the candidates, resolve to it (number plus name together identify it). Would need its own dev measurement first.

## 20. Full pipeline on the quote benchmark, dev split (2026-11-05)

`bench/eval_pipeline_quotes.py --split dev` (logs/pipeline_quotes_dev.txt): 896 items, each written as a draft citation with the judgment's own unique number, its title, the quote and a paragraph reference; AI check off.

- Altered or invented quotes called VERIFIED: 0 of 524.
- Real quotes: 124 of 124 VERIFIED. Invented: 124 MISQUOTE. One-word, negation and number changes: all NEEDS_REVIEW. Splices: 123 MISQUOTE, 1 NEEDS_REVIEW.
- Wrong paragraph far away: 124 of 124 WRONG_PARAGRAPH. Adjacent paragraph (off by one): 123 VERIFIED, 1 WRONG_PARAGRAPH, by design (page breaks shift numbers by one).
- Found by this run: a name like "P. V. Sivarajan v. Union of India" was split at the initial "V." and flagged NAME_MISMATCH on the case's own title (7 items). `split_parties` now skips a "v." that follows a one-letter initial. Resolver dev and pipeline dev numbers unchanged after the fix.
- The quote items are synthetic alterations of real quotes, so this shows the checks work as designed; it is not an estimate of real-world lawyer drafts.

## 21. Citation formats the extractor does not parse (2026-11-05)

Checked on a made-up line of 12 citations. Recognised: SCC, SCC OnLine, AIR, neutral (INSC), SCR including Supplement forms, and now "1976 (2) SCR 100". NOT parsed as a citation number (they fall back to the case name, so the best possible status is NEEDS_REVIEW, never VERIFIED): "(2010) 3 SCC (Cri) 55" and other SCC sub-series, "1995 Supp (3) SCC 100", "2023 (4) SCALE 12", "JT 2005 (3) SC 10". SCC sub-series pages are separate numbering from the main SCC, so mapping them onto the SCC alias table would be wrong. Not measured on real drafts.

## 22. The 22 dev items where the true case is in the corpus but the result is NOT_FOUND_IN_CORPUS (2026-11-05)

Read all 22 (`bench/eval_pipeline.py --split dev`). None is a wrong answer; they are misses of the safe kind. Causes, by count of what I could read from the names: draft name is an acronym or short form (LIC, DDA, CBSE, RBI, Govt. of India); draft name cut by the extractor on a line break or "Ltd." (about 8); stored title differs a lot from the draft's (about 4, e.g. "Osmania University v. Chancellor" vs "D.S. Reddy v. Chancellor, Osmania University"); the SCC number is not in the alias table at all and the name is too different. Not fixed: acronym expansion could raise recall but fuzzy matches can never reach VERIFIED, so the gain is only a better hint in a NEEDS_REVIEW.

## 23. Shared neutral numbers decided by the draft's name (2026-11-05)

`resolve_exact` now picks one judgment among those sharing a neutral number only if the draft's name fits it at least 0.7 AND beats every other candidate by 0.15 (NAME_PICK_MARGIN). Check: for the 96 shared numbers (216 judgments), using each judgment's own title as the draft name: 75 resolved to the right judgment, 141 stayed ambiguous (identical or near-identical names, e.g. repeated orders in one matter), 0 resolved to a wrong one. The resolver dev benchmark is unchanged (90.2% / 0.8% wrong).

Side finding: the identity threshold (0.7 on the average of two parties) is generous when one party is "Union of India" on both sides: "Raja Ram v. Union of India" scores at or above 0.7 against "Bhule Ram v. Union of India". Not changed; tightening it needs its own dev measurement.
