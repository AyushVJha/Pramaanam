# Pramaan (प्रमाण)

Checks the citations in a legal draft against the Supreme Court of India's own judgments. For each
citation it answers: does this judgment exist, is it the case the draft names, do the quoted words
appear in it, at the paragraph cited? It reports evidence, never a verdict on the law. See
[SPEC.md](SPEC.md) for the plan and [docs/CLAIM_CONTRACT.md](docs/CLAIM_CONTRACT.md) for exactly what each
status promises.

**Status: working prototype, not a product.** The test split was run once on 2026-11-05 (results below); nothing was changed afterwards.

## What you get

| Status | Meaning |
|---|---|
| VERIFIED | The citation number is proven to identify a judgment, name and year agree, and any quote is word-for-word. It does **not** say the judgment supports your argument. |
| NEEDS_REVIEW | A person must look: ambiguous or unproven match, near-match quote, one party of the name differs, or a link we are unsure of. |
| MISQUOTE, WRONG_PARAGRAPH, NAME_MISMATCH | Only said when the case is proven by its number and the quote or name is clearly tied to that citation. |
| NOT_FOUND_IN_CORPUS | Not in the dataset. Never "fake": it may be another court, or an SCC/AIR number we cannot map. |
| LOW_FIDELITY_SOURCE | The quote matches except for what looks like scan noise in the source text. |
| UNSUPPORTED, CONTRADICTED | Optional AI second opinion (off by default); it can lower a result, never raise one. |

## Results (dev split, from scripts in this repo)

| Check | Command | Result |
|---|---|---|
| Find the right case from an SCC/AIR number + name (246 items) | `make bench-dev` | 98.0% right case, 0.4% wrong case |
| Whole pipeline on those items, AI check off | `make bench-pipeline` | 150 VERIFIED, 0 on a wrong case |
| Whole pipeline on 896 quote items | `make bench-pipeline-quotes` | 124 of 124 real quotes VERIFIED; 0 of 524 altered or invented quotes VERIFIED |
| 300 whole real judgments fed in as drafts | `scripts/stress_real_text.py 300` | 4,348 mentions; 1,178 VERIFIED; 10 accusations (8 MISQUOTE, 2 NAME_MISMATCH); the 8 MISQUOTEs read by hand are scan noise in the citing text |
| Local AI judge (qwen3:8b), 39 noisy items | `bench/eval_support.py` | 0 of 15 negatives called supported; 41.7% of positives accepted; 20.5% gave no valid answer; median 45 s per item (too slow for live use) |

The benchmarks use synthetic alterations of real quotes and citations printed in real judgments, so
they show the checks behave as designed, not how real lawyers' drafts will fare. Coverage numbers
(150 VERIFIED of 246) are a floor: the benchmark hides the evidence the citing judgment itself printed.

## Results (test split, run once on 2026-11-05)

Output kept in `docs/TEST_RUN_2026-11-05.txt`. Thresholds were fixed on dev before this run and were not changed after it.

| Check | Result |
|---|---|
| Find the right case (667 items, `bench/eval_resolve.py`) | 95.8% right case, 0.4% wrong case (3), the rest missed or ambiguous |
| Whole pipeline on those items, AI check off | 360 VERIFIED; the benchmark counts 1 of them as on a wrong case, but its label looks wrong (below); 24 items the benchmark says are in the corpus came out NOT_FOUND_IN_CORPUS |
| Whole pipeline on 1,991 quote items | 275 of 275 real quotes VERIFIED; 2 of 1,166 altered or invented quotes VERIFIED (both explained below); 275 of 275 invented quotes MISQUOTE |

The 2 "altered quotes VERIFIED" and the 1 "wrong case" were read by hand and are recorded in DATA_NOTES section 33. They are reported here as the benchmark counts them; no label or code was changed to fix them.

## Try it

The web page (`make demo`, then open http://127.0.0.1:8000) has drag-and-drop or paste, a one-click sample (`/?sample`), per-citation cards that put your quotation next to the judgment's own words, and a downloadable annexure. It loads nothing from other sites.


```
uv sync
make data-sample && make db-sample    # a small 2023-only database, about 2 minutes
make test && make lint
uv run pramaan check demo/sample_draft.txt --no-llm
uv run pramaan check demo/mixed_draft.txt --no-llm       # one example of each kind of problem
uv run pramaan check draft.docx --no-llm --format html --out report.html
make demo                                                # web page at http://127.0.0.1:8000
```

Drafts can be .txt, .md, .docx (footnotes included) or a PDF with a text layer. The full corpus
(38,397 judgments) needs `make db` and about 2 GB. Local mode makes no network call.

## Limits you should know

- **Coverage.** The dataset holds Supreme Court judgments only, and SCC/AIR numbers resolve only when
  another judgment printed the pair with an SCR or neutral number. Many SCC/AIR numbers come back
  NOT_FOUND although the judgment is in the corpus ([docs/DATA_NOTES.md](docs/DATA_NOTES.md) 26).
- **Text quality.** The judgments' text is an embedded scan OCR with errors and side notes spliced in.
  A second reading with a layout engine exists but is only built on demand (a whole-corpus run needs
  about 158 hours on a laptop). Human-checked text accuracy is **not measured** yet.
- **Not checked:** the legal argument; "supra", "ibid" and "id."; tables and footnotes inside judgments;
  SCC sub-series (Cri, L&S), SCALE and JT citations; scanned PDF drafts; names typed in lowercase.
- **Names.** Names sharing a common word ("Mohan Lal Sharma" / "Mohan Das") can still pass.
- **Not run:** the Docker image (no Docker on the dev machine), any public deployment.

## Data and credit

Judgments come from the open CC-BY-4.0 dataset
[vanga/indian-supreme-court-judgments](https://github.com/vanga/indian-supreme-court-judgments)
(originally from the Supreme Court's public site). No paid or third-party legal database is used.
