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

## 5. Not yet answered (out of M0 scope, flagged for later)

- Only years 2022–2024 were inspected, per the approved M0 plan. Pre-2023 judgments (before
  the Supreme Court's neutral-citation scheme, per Bar & Bench) may rely on SCC/AIR citations
  that genuinely appear in `citation` for older years — this needs re-checking once the year
  range expands in M1, rather than assuming the 2022–2024 pattern holds further back.
- Row counts per year: 2022 = 1017, 2023 = 856, 2024 = 782.
