# Do AI models catch altered Indian Supreme Court quotes?

Each model is asked, from memory and with no access to the judgment: "is this quotation accurate, word for word?" for 120 dev items (20 each of: real, one word changed, negation, number changed, two passages spliced, invented). Source: `bench/eval_baseline_llm.py`; table built by `bench/make_leaderboard.py`.

| Model | Altered or invented quotes it accepted (of 100) | Real quotes it accepted (of 20) | Usable answers | Note |
|---|---|---|---|---|
| deepseek-chat | 5 | 2 | 120/120 |  |
| deepseek-reasoner | 7 | 8 | 109/120 |  |
| gemini-3.1-flash-lite | 35 | 17 | 120/120 |  |
| gemini-2.5-flash-lite | 0 | 0 | 0/120 | fewer than 90% usable answers: not comparable |
| gemma-4-26b-a4b-it | 0 | 0 | 0/120 | fewer than 90% usable answers: not comparable |
| gemini-3.5-flash-lite | 24 | 10 | 86/120 | fewer than 90% usable answers: not comparable |
| **Pramaan (no AI)** | **0** | **20** | 120/120 | deterministic; reads the judgment |

Not completed (free tier too slow or closed on our key): see `logs/leaderboard_incomplete.txt`. One run per model, dev items only, first 20 per kind.
