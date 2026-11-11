# Pramaan (प्रमाण)

Checks the citations in a legal draft against the Supreme Court of India's own judgments. For each
citation it answers: does this judgment exist, is it the case the draft names, do the quoted words
appear in it, at the paragraph cited? It reports evidence, never a verdict on the law. See
[SPEC.md](SPEC.md) for the plan and [docs/CLAIM_CONTRACT.md](docs/CLAIM_CONTRACT.md) for exactly what each
status promises.

**Live demo: https://pramaanam.duckdns.org/** (free hosting on a 1 GB machine: expect it to be slow at times).

Author: Ayush Vardhan Jha ([LinkedIn](https://www.linkedin.com/in/ayushvjha)). The public site is
shown as "Pramaanam"; the code, package and repo stay `pramaan`.

**Status: working prototype, not a product.** The deterministic checks, the later-treatment flags and an
opt-in, experimental AI reading check are live. The test split was run once on 2026-11-05 (results below);
afterwards the SCR "Suppl." pattern was fixed and the alias table rebuilt (37,926 to 43,034 rows), so those test
numbers are for the earlier version and have **not** been re-run (the test split is run again only once the dev
result is frozen). The AI reading check has **not** been measured on the harder benchmark yet.

## What you get

| Status | Meaning |
|---|---|
| VERIFIED | The citation number is proven to identify a judgment, name and year agree, and any quote is word-for-word. It does **not** say the judgment supports your argument. |
| NEEDS_REVIEW | A person must look: ambiguous or unproven match, near-match quote, one party of the name differs, or a link we are unsure of. |
| MISQUOTE, WRONG_PARAGRAPH, NAME_MISMATCH | Only said when the case is proven by its number and the quote or name is clearly tied to that citation. |
| NOT_FOUND_IN_CORPUS | Not in the dataset. Never "fake": it may be another court, or an SCC/AIR number we cannot map. |
| LOW_FIDELITY_SOURCE | The quote matches except for what looks like scan noise in the source text. |
| UNSUPPORTED, CONTRADICTED | Optional AI reading check (off by default, opt-in on the site); it can lower a result, never raise one. |
| (NEEDS_REVIEW, later treatment) | A later judgment's own headnote marks the case overruled, partly overruled, disapproved or held per incuriam. The note names that judgment. |

## Agents and later treatment

- **Later treatment (no AI).** The Supreme Court's headnotes label the cases a judgment dealt with, for example
  "... - overruled". `data/build_treatments.py` reads those lines, resolves each cited case with the verifier's
  proven-only rules, and stores them (2,683 label rows, about 100 of them "strong"). A strong label moves a
  VERIFIED result to NEEDS_REVIEW with the source judgment named. Many judgments print no such headnote, so
  "no flag" never means "still good law". Precision is not measured on a labelled set: four known pairs were
  checked (three found) and a sample was read by Claude, not by a lawyer.
- **AI reading check (experimental, opt-in).** A small agent (a custom loop in `src/pramaan/agents/`, no
  framework) reads the cited judgment: it searches it, reads paragraphs in full, and says whether the judgment
  supports what the draft says, naming the paragraph it relied on. Code enforces the rules: the answer must point
  at paragraphs the agent read, the quote shown is looked up by code, there are limits on steps, time and cost,
  and a guard (`agents/guard.py`) means an agent can never produce VERIFIED. If the model is down, the
  deterministic result stands. A second agent suggests candidate cases for citations that did not resolve
  (always NEEDS_REVIEW, "not confirmed").
- **Live site:** off unless ticked; the box says what is sent where (the sentence around each citation and
  paragraphs of the judgment go to Google's Gemini API on its free tier, where Google may use inputs to improve
  its models); 4 citations and 150 seconds per request; one agent job at a time; nothing is cached or logged.
- **Model:** any local (Ollama) or OpenAI-style endpoint, set in `.env` (see `.env.example`). The live site uses
  `gemini-3.1-flash-lite`; newer Gemini models were rejected by Gemini's function-call filter or were overloaded
  when tested.

## Results (dev split, from scripts in this repo)

| Check | Command | Result |
|---|---|---|
| Find the right case from an SCC/AIR number + name (246 items) | `make bench-dev` | 98.0% right case, 0.4% wrong case |
| Whole pipeline on those items, AI check off | `make bench-pipeline` | 150 VERIFIED, 0 on a wrong case |
| Whole pipeline on 896 quote items | `make bench-pipeline-quotes` | 124 of 124 real quotes VERIFIED; 0 of 524 altered or invented quotes VERIFIED |
| 300 whole real judgments fed in as drafts | `scripts/stress_real_text.py 300` | 4,348 mentions; 1,178 VERIFIED; 10 accusations (8 MISQUOTE, 2 NAME_MISMATCH); the 8 MISQUOTEs read by hand are scan noise in the citing text |
| Local AI judge (qwen3:8b), 39 noisy items, model copies quotes | `bench/eval_support.py` | 0 of 15 negatives called supported; 41.7% of positives accepted; 20.5% gave no valid answer; median 45 s per item |
| Same items, model names paragraphs and code looks up the quote (`PRAMAAN_SUPPORT_MODE=pointer`) | `bench/eval_support.py` | 1 of 15 negatives called partially supported; 79.2% of positives accepted; 2.6% gave no valid answer; median 61 s per item. One run, small and noisy set, local model |
| Plain LLM as a baseline: "is this quote accurate?" from memory, same 120 dev items (20 per kind) | `bench/eval_baseline_llm.py` | `gemini-3.1-flash-lite` accepted 35 of 100 altered or invented quotes (number changes: 14 of 20) and rejected 3 of 20 real ones; Pramaan VERIFIED 0 of 100 and 20 of 20 real. One run, one small free model, first 20 per kind, AI check off for Pramaan; a stronger model may do better |
| Benchmark v2 (12 per kind: positives, easy and hard negatives), `gemini-3.1-flash-lite`: quote, pointer, agent | `bench/eval_support_v2.py` | **0 of 24 negatives called supported in every mode** (hard negatives included). Positives accepted: quote 0%, pointer 17%, **agent 67%** (gave up 0%). Median seconds 2.2 / 2.8 / 4.1. The agent first scored 0% because of a bug of mine (negative paragraph numbers; see DECISIONS); the fix was found by reading dev transcripts, so 67% is a dev number on 12 noisy positives; the test-split run is below |

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

### Test split re-run on the current code (2026-11-11)

Same held-out items and thresholds, AI check off; output in `docs/TEST_RERUN_2026-11-11.txt`. Compared with the
run of 2026-11-05: right case 641 of 667 (96.1%, was 95.8%), wrong case 3 (unchanged); real quotes 272 of 275
VERIFIED, the other 3 are NEEDS_REVIEW because a later judgment's headnote marks the case overruled or
per incuriam (the quote itself is still verbatim); altered or invented quotes VERIFIED: 1 of 1,166 (was 2). The
1 remaining is a negation that the checker accepts as verbatim; it is not hidden.

### AI support check, benchmark v2 test split (run once, 2026-11-11)

`gemini-3.1-flash-lite`, 78 items (40 positives, 16 easy and 22 hard negatives), settings fixed on dev
beforehand and not changed after. Outputs: `docs/SUPPORT_V2_TEST_*.txt`.

| Mode | Wrong propositions called supported (of 38) | True positives accepted (of 40) | No valid answer on positives | Median seconds |
|---|---|---|---|---|
| quote (model copies quotes) | 0 | 7.5% | 80% | 2.5 |
| pointer (model names paragraphs) | 0 | 27.5% | 55% | 1.7 |
| **agent (searches, reads, then answers)** | **0** | **75%** | 10% | 4.2 |

The positives are noisy by construction (a sentence that cited a case does not always state what the
case held), so read 75% as "at least". One run, one small free model; the agent prompt and tools were
fixed on dev (including the negative-paragraph-number fix) before this run.

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

## Use it from another AI assistant (MCP)

Pramaan also runs as an [MCP](https://modelcontextprotocol.io) server, so an assistant such as Claude
Desktop or Cursor can check a citation before it states it. Only the deterministic checks run: no model
call, no network, no cost. It needs the full database (`make db`).

```
uv sync --extra mcp
# add to the assistant's MCP config:
{"mcpServers": {"pramaan": {"command": "uv",
  "args": ["run", "--extra", "mcp", "python", "-m", "pramaan.mcp_server"],
  "cwd": "/path/to/Pramaan"}}}
```

Tools: `verify_citations(text)` and `verify_quote(case_name, citation, quote)`. They return the same
statuses as the web page. Tested over a real stdio session; not yet tried inside Claude Desktop or Cursor.

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
- **AI reading check:** experimental and not yet measured; it is only as good as a small free model, can be
  slow or unavailable, and its one-sentence reasons are model text, so read the paragraph it quotes.
- **Deployment:** runs natively (no Docker) on an Oracle Cloud free VM with 1 GB RAM behind Caddy; see
  [DEPLOY_ORACLE.md](DEPLOY_ORACLE.md). The Docker image was never built. No monitoring, backups or load test.

## Data and credit

Judgments come from the open CC-BY-4.0 dataset
[vanga/indian-supreme-court-judgments](https://github.com/vanga/indian-supreme-court-judgments)
(originally from the Supreme Court's public site). No paid or third-party legal database is used.
