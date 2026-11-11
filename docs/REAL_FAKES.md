# Real reported fabricated citations (small, hand-collected)

What this is: citations that Indian courts have said, in public orders, were fabricated, run through the checker with the AI check off. `bench/real_fakes/items.jsonl` holds the items with their sources; `bench/eval_real_fakes.py` re-runs them; the output is `bench/results/real_fakes.json`.

What this is not: a benchmark. It has **6 items**, nothing was tuned on it, and it is far too small for a rate. It exists so that "the test set is only synthetic" is no longer the whole story.

## Result (checker only, no AI)

| Item | What the court or press said | Pramaan said |
|---|---|---|
| Subramani v. M. Natarajan (2013) 14 SCC 95 | one of four decisions in a trial court order that the Supreme Court called non-existent, fake or synthetic (order of 27 Feb 2026) | NOT_FOUND_IN_CORPUS |
| Chidambaram Pillai v. SAL Ramasamy (1071) 2 SCC 68 | same four (the order prints the year as "1071") | NOT_FOUND_IN_CORPUS |
| Lakshmi Devi v. K. Prabha (2006) 5 SCC 551 | same four | NOT_FOUND_IN_CORPUS |
| Gajanan v. Ramdas (2015) 6 SCC 223 | same four | NOT_FOUND_IN_CORPUS |
| Chitra Narain v. DDA, 2000 (87) DLT 276 | reported by LiveLaw as non-existent (Delhi High Court, Sept 2025) | NOT_FOUND_IN_CORPUS |
| Raj Narain v. Indira Nehru Gandhi (1972) 3 SCC 850, paras 73 and 74 | real case; press reports say the petition quoted paragraphs the judgment does not have | VERIFIED (case exists) |

**Count:** 0 of 5 reported-non-existent citations were marked VERIFIED. Not one was called "fake", which is intended: NOT_FOUND_IN_CORPUS means "we could not find it", not "it does not exist".

## What this does not show

- **The four Supreme Court items are not individually confirmed.** The order names four decisions and says the trial court deployed "non-existing, fake or synthetic alleged judgments". It does not say, item by item, which of the four is wholly non-existent. NOT_FOUND_IN_CORPUS is therefore the right answer for any of them, and I did not check whether any exists in a law report.
- **The Delhi item is trivially outside the corpus.** It is a High Court reporter citation and the corpus is Supreme Court only.
- **The invented-paragraph case is not caught.** The checker only tests a paragraph reference when a quote comes with it. A bare "paragraphs 73 and 74" on a real case gets VERIFIED for the case and no warning on the paragraph. A simple rule ("flag paragraph numbers above the highest stored") would be unreliable: for this very judgment the database stores numbered paragraphs only up to 6, because long multi-opinion judgments are not numbered the way the splitter expects, so the rule would flag correct citations of other long judgments. This is a known gap, not a fixed one.

## Items looked at and left out

- **Pooja Ramesh Singh v. J&K Bank (2026 INSC 668, six citations):** two press summaries name the six citations differently, and the judgment text was not retrievable, so I included none of them.
- **Vijay Ghanshyam Gadiya (2026 INSC 947), Quanta Logistics (Bombay HC), Buckeye Trust (ITAT), KMG Wires (Bombay HC), Karnataka HC (Sammaan Capital):** the order texts I could read (Gadiya, Quanta) name no citations; for the others the page I could open did not list them.

## How to add more

Add a line to `bench/real_fakes/items.jsonl` with the sentence as it would appear in a draft and a public source that names the citation. Only the court's order or a named press report belongs there; anything not named in a source stays out.
