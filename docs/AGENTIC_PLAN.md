# Agentic workflow plan

Written 2026-11-05. Status: phase A built and tested; B to G not started. Nothing here runs on the live site.

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
- G. Treatment check (is the case later overruled/distinguished), later.

## Cost and time
Local model runs are free (about 45 s per item). Any paid API run needs an estimate first; above $2 ask.
The live 1 GB server cannot run a local model, so agents there would need an API key and an explicit decision.

## Not measured yet
Agent accuracy, agent cost per citation, latency under the runtime. All numbers will come from scripts in this repo.
