# Agentic workflow plan

Written 2026-11-05. Status (2026-11-05): phases A to F are built and tested with a fake model (370 tests). Phase B and the v2
comparison (C, D) are being measured on dev with a local model; results are added below when they exist.
E (locator) is built but not yet measured. Nothing here runs on the live site.

## Why (measured, not assumed)
The support judge (checks/support.py) reads the top five BM25 paragraphs and answers once. On 39 noisy dev
items with local qwen3:8b: 0 of 15 negatives called supported (good), 41.7% of 24 positives accepted,
20.5% of answers unusable. Every unusable answer was "quote not found word for word": the model understood
but mis-copied the evidence. The dev set is also too easy to tell a better method from a worse one.
So the first fixes are not "more agents"; they are (B) stop asking the model to copy text, and (C) a harder test.

## Principles (each is enforced in code, not in a prompt)
1. VERIFIED comes only from deterministic proof. An agent can never set it (`agents/guard.py`, tested over every status pair).
2. Agents may only move a result toward more care: NEEDS_REVIEW, UNSUPPORTED, CONTRADICTED, CANNOT_VERIFY.
3. Tools are read-only (sqlite opened `mode=ro`). Tool output is evidence, never instructions.
4. Hard budgets per run: steps, seconds, dollars, observation length (`Budget`). Exceeding one ends the run with a named status.
5. Evidence is checked by code (`verify`) before an answer is accepted; one correction turn, then give up honestly.
6. No framework: a ~100-line loop that can be read and defended line by line.
7. Every LLM call goes through llm/client.py (cache, cost log).
8. An agent ships only if it beats the single-shot baseline on `dev` with no rise in false accusations; the test split is run once.

## Phases
- A. Runtime + guard + tests. DONE (agents/runtime.py, agents/guard.py, tests/test_agent_runtime.py).
- B. Evidence by pointer: the model names paragraph numbers (and a short phrase); code looks the text up and
  checks it. Removes the copy-failure class. Measure on dev with local qwen3:8b (free), compare with current judge.
- C. Support benchmark v2: gold paragraph taken from pinpoint citations in real judgments, plus hard negatives
  (right case wrong proposition, neighbouring paragraph). Freeze dev/test before any tuning.
- D. Reading agent for the support check (tools: search paragraphs, read paragraph, read neighbours) against the
  single-shot baseline on v2 dev.
- E. Locator agent for citations not resolved: proposes candidates, result is NEEDS_REVIEW only, never VERIFIED.
- F. Orchestrator, trace panel in the report, cost caps; agents stay off on the live site until measured.
- G. Treatment check (is the case later overruled/distinguished). DONE in a deterministic form, no model:
  `data/build_treatments.py`, `checks/treatment.py` (headnote labels written by the court).

## Cost and time
Local model runs are free (about 45 s per item). Any paid API run needs an estimate first; above $2 ask.
The live 1 GB server cannot run a local model, so agents there would need an API key and an explicit decision.

## Not measured yet
Agent accuracy, agent cost per citation, latency under the runtime. All numbers will come from scripts in this repo.

## What exists now
- `agents/runtime.py` loop, `agents/guard.py` status guard.
- `agents/tools.py`: `JudgmentReader` (search_judgment, read_paragraph) and `CaseFinder` (find_by_party_names,
  find_by_citation, find_by_text, case_info). Both remember what they showed the model.
- `agents/support_agent.py`: reading agent. Answer is paragraph numbers; each must have been READ in full;
  "not supported" needs a search; the quote shown is looked up by code. Same `SupportResult` as the single-shot judge.
- `agents/locator.py`: suggests up to 3 case ids that a tool showed it. Only ever NOT_FOUND to NEEDS_REVIEW.
- `agents/orchestrator.py`: deterministic first, then agents, then the guard; draft budget (calls, dollars, seconds);
  any agent failure keeps the deterministic report. CLI: `pramaan check draft.txt --agents`.
- Report: "How the agents checked" section lists each tool call and the final answer.
- `bench/build_support_v2.py`, `bench/eval_support_v2.py`: benchmark v2 (positive, easy negative, HARD negative =
  right case, wrong proposition) and a runner for modes quote, pointer, agent. `scripts/queue_support_v2.sh` runs
  the three in sequence on the local model.

## Measurements (filled in from logs/, never typed by hand)
### Phase B: evidence by pointer, v1 dev set (39 items, qwen3:8b local), logs/support_qwen3_8b*.json
| | quote (copy text) | pointer (name paragraphs) |
|---|---|---|
| positives accepted (24, noisy) | 41.7% (10) | 79.2% (19) |
| negatives called supported/partial/contradicted (15) | 0.0% (0) | 6.7% (1) |
| no valid answer | 20.5% (8) | 2.6% (1) |
| needed a retry | 33.3% | 2.6% |
| median seconds per item | 45 | 61 |
Reading: the copy-failure class is gone (gave-up 20.5% to 2.6%) and positives are accepted far more often.
The cost: one negative (item e7e3d040ebba-neg) was judged partially_supported. In the old mode part of the
"0 false support" came from the 20.5% of answers that were thrown away, which count as safe. With 15 negatives
one item is 6.7 points, so this is not a reliable estimate of the true rate. In the pipeline, partially_supported
only gives NEEDS_REVIEW (never an accusation and never a tick), so the effect is an extra review, not a wrong verdict.
Dev only, one run, one local model, noisy positives. Not a published result.
### Phase C: benchmark v2 built (dev only): 22 positives, 13 easy negatives, 16 hard negatives
First version had a flaw found by reading it: every hard negative reused one noisy headnote line. Fixed: each
proposition is used once, must be short with no treatment labels, and is ranked by the share of its topic words found
in the case text. Contexts are the dataset's raw slices (some start mid-citation), so v2 is still a noisy dev yardstick.
### Phase D (three modes on v2): not yet measured
The local model is too slow for the agent mode (about 60 s per call). Waiting for a faster free model (Gemini
free tier) before running `scripts/queue_support_v2.sh` equivalents.

## Rules for turning agents on in the product
1. The agent beats single-shot on v2 dev: same or lower false_support on hard negatives, higher accepted on positives.
2. Median time and cost per citation are known and acceptable (local: minutes; API: measure first, ask above $2).
3. Test split run once, after the dev result is frozen, with the user's go-ahead.
4. Live site: behind a password and a daily cap first. Not before.

## Not built yet
Treatment check (G); a gold-paragraph set (pinpoint citations are too rare in dev: 7 of 247 items);
parallel agent runs; a trace viewer in the web page.


## Benchmark v2 result (2026-11-06, dev, gemini-3.1-flash-lite, 12 per kind)
quote / pointer / agent: negatives called supported 0/24 in all; positives accepted 0% / 16.7% / 0%; gave up on positives 58% / 42% / 25%; median seconds 2.2 / 2.8 / 5.4. The model is cautious: the agent never said supported on a positive. Not yet investigated why (noisy positives vs prompt vs model). Source: logs/v2_*.out and logs/support_v2_*.json. Nothing was tuned on these results.


### Update: negative paragraph numbers (2026-11-06)
The 0% agent result above was my bug: judgments have negative paragraph numbers (front matter), the model read `[para -2]` as a dash and asked for paragraph 2, which did not exist. After the fix (a hint from the tool, one prompt line) the same 12+12+12 dev items gave: negatives called supported 0/24; positives accepted 8/12 (66.7%); gave up 0%; median 4.1 s. The bug was found by reading transcripts of dev items, so this is tuned on dev; test has not been run. Logs: logs/v2_agent*.out.
