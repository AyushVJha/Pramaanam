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

## M1 — Corpus database

**1. Your paragraph splitter misses the opening paragraphs on 15% of a 20-judgment
spot-check. Why ship it instead of fixing it?**
Because the failure mode is well understood and narrow: it only happens when a judgment
quotes another case's own numbered paragraphs at length, and the quoted numbering happens
to form a longer monotonic run than the judgment's real (but short) opening sequence. I
measured the rate (3/20) rather than guessing, wrote a test that locks in and explains the
exact behavior on a real example (`2023_15_848_865_EN.pdf`, quoting an affidavit's own
"4.-7." numbering), and documented the downstream consequence for M4 (a cited "para 3"
could false-negative if paragraph 3 was in the discarded opening section). Engineering a
perfect fix — e.g. detecting quotation marks/indentation to disambiguate — is future work,
not something M1's acceptance criteria asked for.

**2. Why key `case_citations`/`paragraphs` on a column literally named `case_id` when
M0 told you not to trust that name?**
Because that's the column *name* SPEC.md §3.4's schema sketch uses for the foreign key,
not the metadata field I was warned about. I kept the name for spec fidelity but populate
it with `cnr` (the real stable key), and said so explicitly in a code comment and in
DECISIONS.md — the point of the M0 finding was "don't trust `case_id`'s *contents*", not
"never use that identifier as a name."

**3. Two cases ended up with zero paragraphs. How did you know that was a real data gap
and not a bug in your extraction code?**
I didn't assume — I checked. Both cases' derived PDF filenames weren't present in
`english.tar`'s member list, and the tar's own `english.index.json` reports
`file_count: 854` against 856 metadata rows — exactly a 2-row gap. If it had instead been
a PyMuPDF exception or an empty-but-present PDF, the `_case_paragraphs` exception handler
would have logged a warning with a traceback, which it didn't for these two.

**4. Why does `build_db.py` drop and rebuild every table from scratch instead of
upserting?**
"Idempotent" here just needs re-running `make db-sample`/`make db` to produce the same
result, not fast incremental updates. At this corpus's scale (thousands of cases, not
millions), a full rebuild is cheap enough and trivially correct — no stale-row or
partial-update bugs to reason about. It would need to change if the full 2010-2025 build
became too slow to iterate on.

**5. Why SQLite with FTS5 instead of Postgres, given you know Postgres from your job?**
One file, no server process, free to host alongside the HF dataset, and FTS5's BM25 +
trigram tokenizer cover everything the resolver (M3) and support judge's retrieval (M5)
need without standing up infrastructure for what's currently a single-writer, thousands-
of-rows corpus. I recorded in DECISIONS.md that this would move to Postgres + `pg_trgm` +
`pgvector` at real scale — the choice is about matching infra to the actual problem size,
not avoiding Postgres.

## M2 — Citation extraction

**1. M0 found zero SCC/AIR citations in our metadata. How did you get real SCC/AIR test
strings for M2 without inventing them?**
I looked in the right place: M0's "zero SCC/AIR" finding was about the `citation` metadata
field, which only records a judgment's citation of *itself*. The judgment's own *body
text* cites other precedents in every format — a corpus-wide scan found 3,445 real SCC
strings, 458 AIR strings, and 163 SCC OnLine strings sitting in paragraph text (e.g. "AIR
2005 SC 626" inside a sentence quoting *Bhanu Kumar Jain v. Archana Kumar*). All of
`test_patterns.py`'s positives for those three formats come from that scan, not from
public-knowledge landmark cases or anything invented.

**2. Your case-name regex initially matched a party name AND ran straight into the next
citation's digits. What was wrong, and how did you know?**
Appendix A's suggested character class for the name parts was `[\w.&,'\- ]`, which
includes digits and commas — so on real text like "Archana Kumar, AIR 2005 SC 626" the
match didn't stop at the comma, it kept consuming through "AIR 2005 SC 626" too, because
digits are `\w`. I caught it by actually running extraction against real corpus text
instead of trusting the pattern because it came from the spec — the fix excludes digits
and commas from that character class.

**3. The case-name format still has known false positives. What are they, and why ship
it anyway?**
Running the extractor across 15 real paragraphs surfaced two recurring patterns: (a) a
judgment's own case-name header getting matched as if it cited a *different* case, and
(b) a short run of capitalized words right before "v." occasionally passing the
capitalization-ratio filter even when it's actually a sentence fragment (e.g. "...General
sought to refer to Rameshwar & Ors. v. State of Haryana"). Both are measured, named
limitations, not swept under the rug — and this exact format is the one SPEC.md itself
flags as needing an LLM fallback for real precision, which isn't built until M5+. Shipping
a heuristic-only version now and measuring its actual precision via hand-marking (rather
than either blocking on M5 or guessing at a number) is the honest middle path.

**4. Why didn't you just have the AI generate the extraction gold labels — wouldn't that
be faster?**
Because PROMPTS.md is explicit that this is the one thing I must never do: "This is your
gold data — never let the AI label it for you." If I labeled my own extractor's output,
any error pattern my code is blind to would never get caught — the whole point of a human
in the loop is to catch exactly the mistakes the system that produced the candidates can't
see in itself. I built the CLI, picked a representative (not cherry-picked) sample of 10
judgments by candidate count, and the actual correct/incorrect judgment is entirely yours.

**5. Your "recall" measurement only catches misses containing "SCC"/"AIR"/"INSC"/"SCR" —
isn't that going to overstate recall?**
Yes, and I say so directly rather than letting the number imply more than it measures:
it's a lower bound on recall for the 5 structured formats, and explicitly "not measured"
for case names, where there's no reliable token to scan for. A full re-read of 10
judgments for exhaustive recall would blow well past PROMPTS.md's ~1 hour estimate for
this task; the token-scan is a deliberate, stated trade-off between thoroughness and the
time budget — not an attempt to make the number look better than it is.

**6. The user caught a false positive on the very first candidate they looked at, before
any formal labeling happened. What was it, and what does it say about your process?**
A judgment's own title repeats as a running header/footer throughout the printed SCR
volume (print convention), and PyMuPDF's plain-text extraction interleaves that into the
body text with no structural marker separating it from real content — so the extractor
mistook the judgment's own header for a citation to a *different* case. The useful signal
wasn't the bug itself (regex-based extraction on real legal text was always going to have
edge cases) — it's that a single real example, actually read end-to-end with the user
before any bulk labeling started, surfaced a systematic root cause in under five minutes
that could have otherwise consumed a meaningful fraction of the 100 hand-marked labels as
one-off "incorrect" marks. I fixed the root cause in `pdf_text.py` rather than treating it
as 15+ individual labeling annoyances, and measured the fix's actual impact (0 remaining
own-title leaks across 150 re-scanned judgments) instead of assuming it worked.

**7. Why does the footer-stripping fix need a *different*, unbounded regex instead of
reusing `citations.patterns.CASE_NAME`?**
Because the two use cases have different risk profiles. `CASE_NAME` is capped at 8 words
per side specifically to stop it from swallowing a whole preceding sentence when scanning
arbitrary draft text for *any* case name (SPEC.md's own "high recall, low precision"
format). The footer-stripper doesn't have that risk the same way — it only deletes a match
if it *also* fuzzy-matches the case's own known petitioner/respondent names above an 80%
threshold, so an unbounded match is safe there and necessary: this case's own corporate
party name is 10 words long ("GODREJ AND BOYCE MANUFACTURING COMPANY LIMITED THROUGH ITS
CONSTITUTED ATTORNEY"), and the 8-word cap was truncating it, leaving a dangling fragment
behind. Same literal problem (matching "X v. Y"), different constraints, so a second,
purpose-built pattern was the right call rather than forcing one regex to serve both.

---

## M3: Resolver and identity check

**1. Why does the resolver refuse to pick a case sometimes? Isn't a best guess more useful?**
Because the report would mark a bad citation VERIFIED. A wrong match is worse than a miss: a miss becomes NOT_FOUND_IN_CORPUS, which the user checks by hand, while a wrong match hides the problem. So a number shared by several cases, a tie the year cannot break, and a name that is only "Ltd." all return no match. On the test split 0.7% of citations resolve to a wrong case and 13.8% are missed. I accept that trade on purpose.

**2. How did you get ground truth without hand-labelling 900 citations?**
Judgments write parallel citations, like "Name, (2001) 2 SCC 386 : [2001] 1 SCR 1". The SCR number identifies the case by exact lookup. I hide it and test whether the resolver finds the same case from the SCC number and the name. The weakness is that the answer key depends on the parallel number being right. I found a mistyped number making a wrong key, so I dropped the "anchor not found" class from scoring and measured false matches by hiding the true case instead.

**3. How did you choose the 0.85 threshold, and how do you know you did not overfit?**
I swept it on the dev split only. Wrong-case answers stay at 1.2% from 0.70 up, so the threshold mostly trades correct answers against lookalike matches. 0.85 is where the curve bends. Test was run after the threshold was fixed and gave the same 85.0% correct, within a point on every measure. I also revised the benchmark builder after reading dev errors, and I say so in DECISIONS.md. Test was only used to check the benchmark's "anchor not found" labels, not to change the resolver.

**4. Your first results looked worse than the final ones. What changed?**
Three real bugs, found by reading dev failures. First, the year column is the law-report volume year for 13% of cases, so a case decided in December 1954 was filed under 1955 and a citation saying 1954 missed it. I now use the decision date. Second, my benchmark paired footnote numbers with the wrong case name. Third, the resolver picked words from a set in random order, so results varied between runs. I fixed it and checked three different hash seeds.

**5. Why not use embeddings or an LLM for matching names?**
Names are short and the failures are mostly structural: abbreviations, "& Ors.", truncated parties, same-party cases in nearby years. A year filter plus character-level matching is cheap, runs in milliseconds, and I can explain every score. An embedding would not separate two cases with the same parties in different years, which is the main remaining error. An LLM would add cost and non-determinism for little gain here. I would reconsider it only to read the paragraph context for same-party twins.

---

## M4: Quote and paragraph checks

**1. Why did you not use `partial_ratio` over every paragraph, as the spec says?**
I did, first. It ran over ten minutes on one judgment because the last numbered paragraph of some judgments holds 2.7 million characters (it swallows everything after the last numbered paragraph). I replaced it with an index of shared four-word runs. Each run votes for where the quote starts, and only that stretch is scored with rapidfuzz. The result takes 0.2 seconds on the largest case and gives the same statuses on the benchmark.

**2. A near match is not a misquote. How do you tell an OCR slip from a deliberate change?**
I cannot from the score alone, and I say so. The check lists the exact changed words and flags a changed negation or number, because those are the changes that flip meaning. A changed adjective is a near match with the diff shown. The support judge in M5 reads meaning. On real quotes from old cases, near matches are common and mostly harmless, so M7 must not map near match to MISQUOTE.

**3. Your benchmark scores are close to 100%. Why should I believe that?**
You should not read it as real-world accuracy. The "real" quotes are copied from the same text the checker reads, so OCR and typing never differ. The scores show the logic works on altered quotes: a swapped word, an added negation, a changed number, a splice. For realism I measured quotes real judgments take from other judgments. Only 3.4% matched word for word, and I explain in the notes why that is not a misquote rate either. Realistic hallucinations are M6.

**4. You found a weakness in the test split. Why did you not fix it?**
Because I found it by reading test failures, so fixing it would make the test number mean less. Pieces of fewer than four words after a "...." are ignored, so a real first half plus a short junk tail can pass. It hit 1 of 1,166 altered quotes. I documented it in DECISIONS.md and left it for a decision on a fresh split. Rule: tune and fix on dev, then read test once.

**5. Why is the threshold 85 and not 80 or 90?**
A dev-only sweep. Spliced quotes are the hard case, because half a quote scores around 50 to 60 and the other half is invented. At 80, 2.4% of splices passed as near matches. At 85, 0.8% did. From 85 to 90 nothing changed. At 95, one-word changes in short quotes started to fall out and become not found (83% right). 85 is the lowest value that rejects splices reliably.

---

## M5: Support judge

**1. How do you stop the judge inventing evidence?**
The prompt demands verbatim quotes, but I do not rely on that. After every answer, code checks that each quote occurs in the paragraph the judge named, using the same lowercase-words comparison as the quote check. An invented quote fails, the model is told exactly what was wrong and gets one retry, and a second failure becomes `cannot_determine`. A supported verdict with no evidence is also rejected. The judge's confidence never reaches the report without proof.

**2. Why did you not use FTS5 for retrieval, as the spec says?**
I measured it. Searching the full corpus table and then filtering to one case took about 3 seconds a query, because FTS5 scores every match across 38,000 judgments first. After resolution I only need one judgment, a few hundred paragraphs, so I rank those in Python with a short BM25. It is instant and the word weights come from that judgment. The cost is that it matches words, not meaning. Whether the right paragraph lands in the top five is not measured until the benchmark exists.

**3. Why retrieve only from the resolved judgment? Wouldn't a global search find more?**
It would find more, and that is the problem. If the cited case is wrong, a global search finds another judgment that does support the claim and the tool would say "supported". Scoping to the resolved case means the question asked is exactly "does this case say this", and it removes the cost of a global index. The risk moves to the resolver, which is why identity is checked before support.

**4. What happens when the model is down, malformed or refuses?**
The function never raises on bad output. Invalid JSON, a wrong shape or an unverifiable quote all end in `cannot_determine`, which the report shows as NEEDS_REVIEW. The SDK itself retries rate limits and server errors. Every call, cached or not, is logged to `logs/llm_usage.jsonl`, so a run's cost can be audited afterwards.

**5. How do you know it works? What did you measure?**
Honestly: the logic is tested with a fake model (retrieval ranking, JSON parsing, quote verification, retry, every status mapping), 139 tests in all. No real model has been run yet, so I have no accuracy, cost or latency number, and I say so in the README. The first real numbers will come from the 10-item dev run and then from the M6 benchmark. Tuning of prompt and model happens on dev only.


---

## Resolver extension: SCC / AIR aliases

**1. Where does an SCC to case mapping come from if the dataset has no SCC numbers?**
From the judgments themselves. They print "(2001) 2 SCC 386 : [2001] 1 SCR 1". The SCR number finds the case by exact lookup, so the SCC number beside it names the same case. I mine every such pair into a table. No third-party site is used.

**2. How do you know it is right?**
Two checks. Of the 390 numbers printed in two or more judgments, 385 agree on one case. And I built the map from 70% of the citing judgments and tested on the rest: 99.0% of answers were right (199 of 201). Caveat: the truth there is the same kind of printed pair, so it measures agreement, not independent proof.

**3. Why did dev go from 85.0% to 90.7% and not more?**
The table only knows numbers that a judgment prints next to a number the dataset has. That is 1,839 numbers in all, so 26.6% of held-out citations were covered. The rest still use fuzzy names.

**4. Isn't it circular to test on the same judgments that built the map?**
It would be, so each evaluation item hides the evidence its own citing judgment printed. Without that the item would be answered from its own text. The test split has not been run with this step.

**5. What if two judgments disagree on a number?**
The step refuses and falls through to fuzzy matching. 5 of 390 repeated numbers conflicted. I never pick a winner by count, because a typo repeated in two places would then win.

## Verdict redesign (step 7): five likely questions
1. **Why can VERIFIED be given without the AI?** Because the claim is narrow: the citation exists, identity and quotes check out. These are deterministic string/DB checks. The AI cannot be trusted with a green tick.
2. **Why can the AI still downgrade?** A warning costs a lawyer a minute of reading; a false tick costs a court. Evidence quotes are verified to exist before the warning counts.
3. **What is "proven"?** Exact neutral/SCR number, or an SCC/AIR pair printed in at least 2 other judgments. One judgment can hold a typo (the Basheer case, DATA_NOTES 15).
4. **Why LOW_FIDELITY_SOURCE?** The dataset text is scanned OCR. A one-word near-match that looks like OCR noise is not evidence of a misquote.
5. **Is the witness threshold of 2 tuned?** No, it is a conservative constant; its effect is measured on dev only (scripts/alias_witness_dev.py).

## Hardening after real-text testing (name, quote and link rules): five likely questions
1. **Why do you test on a real judgment's text as if it were a draft?** Synthetic benchmarks only prove the checks do what I designed. A real 410,000-character judgment produced 4 accusations on text that is presumably accurate, which found three bugs the benchmarks could not: names attached across footnote numbers, quotes paired with citations a sentence away, and abbreviated names scoring low.
2. **What does `name_tight` / `quote_tight` mean?** Whether the name or quote clearly belongs to this citation: no digit between name and citation, and a quote within 100 characters. A loose link can still give a tick (claims stay true) but cannot accuse; accusing on a guess about which text belongs to which citation is the worse error.
3. **Why is NAME_MISMATCH only below 0.5 when the match bar is 0.7?** Because an accusation costs more than a review. On dev, 0.7 wrongly accused 17 of 246 correct names (abbreviations, garbled extraction); 0.5 wrongly accused 3 and still caught 96% of random wrong names. In between, the report says "check for an abbreviation".
4. **How do you stop "Raja Ram v. Union of India" being ticked as "Bhule Ram v. Union of India"?** VERIFIED needs both parties to clear a bar (0.6, chosen on dev). It cuts wrong names ticked from 14 of 73 to 3 of 73. A shared common word (Ram, Singh) still gets through sometimes; I say so in DATA_NOTES.
5. **Why not build more SCC/AIR coverage from case names?** Measured: 95.4% right on 109 checkable cases, which is not proof and could never earn VERIFIED, and it only helps drafts that give a number without a name. Not built; the probe script is kept.

## Paragraph splitting fix (text outside numbered paragraphs)

1. **How did you find the bug?** By comparing one judgment's PDF text (6.7k characters) with what the database held (499). The benchmarks could not show it because they are made from the stored text.
2. **Why negative paragraph numbers?** Real paragraph numbers are positive, so negatives never clash with them, stay unique per case and keep reading order; the paragraph check can simply ignore them.
3. **Why did the resolver improve so much?** The printed SCC/AIR citations in the opening text of judgments were never read, so alias evidence grew from 2,800 to 37,926 rows. It is the same rule (an alias needs two other judgments printing it), with more evidence.
4. **Why did accusations go up on the stress test?** More citations now resolve, so more are checked (4,348 mentions instead of 2,642). Rate went from about 0.1% to 0.2%, mostly scan noise in the citing text; I added a fragment rule and paragraph-number stripping and report what remains as not individually resolved.
5. **Is the rebuilt database safe to trust?** Hard invariants pass, the old database is backed up, dev results did not regress, and the test split has not been run.

## Agentic layer (phases A to F)
1. **Why not LangGraph or a framework?** The loop is about 100 lines and every safety rule (budgets, repeated-call stop, answer check, one correction) is visible and tested with a fake model. A framework would hide those rules, and I could not defend them line by line. The tools and verifiers are plain functions a framework could call later.
2. **How do you know an agent cannot give a false green tick?** `guard.allowed_change` only lets agents move toward NEEDS_REVIEW, UNSUPPORTED, CONTRADICTED or CANNOT_VERIFY, never to VERIFIED, and a test checks every pair of statuses. The orchestrator applies it to the final report, and an agent failure keeps the deterministic result.
3. **Why "evidence by pointer"?** In the first judge 20.5% of answers were discarded because the model mis-copied a quote. Now the model names paragraph numbers and code looks up the sentence. It cannot fabricate a quote, and the number must refer to a paragraph the agent read in full.
4. **How do you stop runaway cost or time?** Per-run limits on steps, seconds, dollars and observation length; a draft-level limit on how many citations get agent work, total dollars and seconds; the same tool call twice ends the run. Hitting a limit gives a named status and the deterministic report stays.
5. **What is the hard-negative set and what is its weakness?** A real case paired with a proposition cited to another case, chosen for word overlap and a 10-year gap, so labels need no model. It is noisy: a case can happen to say the same thing, so a "supported" there is a flag to inspect, not a proven error. Results are dev only, test is run once.

## Later-treatment flags (overruled / disapproved): five likely questions
1. **How do you know a case was overruled without asking a model?** The court prints it: headnotes list cited cases with labels such as "- overruled". I parse "<citation> - <label>", resolve the citation with the same proven-only rule as the verifier, and store the source line. No model is involved, so it is repeatable and every flag can be read.
2. **What is the main way this goes wrong, and how did you find it?** A label applied to the wrong case. A first spot-check showed a case marked "referred to" inheriting the next case's "overruled". The fix is that neutral labels close the group of citations before them; two tests cover it. I re-built the table and re-read a sample after the fix.
3. **Does "no flag" mean the case is good law?** No. Only judgments with such a headnote contribute (about 2,700 label rows, around 100 strong, in 38,397 judgments), and running-text treatments are not read. The product says "check", never "valid".
4. **Why NEEDS_REVIEW and not a new status?** SPEC 4.1 fixes the status names, and the case does exist. The reason line names the later judgment and the label; an overruled case may be cited on purpose (historically), so a person decides.
5. **Is the precision measured?** Not on a labelled set. I checked four known pairs (three found, one absent: coverage gap) and read a sample of 30 strong rows. That sample was read by Claude, not a lawyer, and is recorded as such. A lawyer-labelled sample is the next step.

## Measured: pointer evidence vs copied quotes (dev, 39 items): five likely questions
1. **What did you measure and what changed?** The same 39 items, same local model, two ways of giving evidence. Unusable answers fell from 20.5% to 2.6%, and positives accepted rose from 41.7% to 79.2%.
2. **Did anything get worse?** One of 15 negatives was called partially_supported where the old mode had none. I report it. The old zero was helped by discarded answers counting as safe, and 1 of 15 is too few to estimate a rate.
3. **Why is that acceptable?** partially_supported only yields NEEDS_REVIEW. The AI cannot create a tick or an accusation on its own, so the worst case is an extra look by a person.
4. **How trustworthy is the positive set?** Not very: positives are sentences that cited the case, and some cite it only to set it aside. So 79.2% is not an accuracy figure; it is a comparison between two methods on the same noisy items.
5. **What is next?** Benchmark v2 adds hard negatives (right case, wrong proposition) and compares quote, pointer and the reading agent. It needs a faster free model than my laptop's 60 s per call.

## Benchmark v2, plain-LLM baseline and leaderboard: five likely questions
1. **What does benchmark v2 test that the quote benchmark does not?** Whether a proposition is supported by the cited case. Positives are real sentences that cited the case; easy negatives pair the case with an unrelated proposition; hard negatives pair it with a proposition cited to another case, chosen by word overlap and a 10-year gap. Labels come from structure, not from a model.
2. **How did you avoid tuning on the test split?** Prompts, paragraph handling and budgets were tuned on the 51 dev items. The 78-item test file was built once and run once per mode (quote 7.5%, pointer 27.5%, agent 75% positives accepted; 0 of 38 negatives called supported in all modes). The agent number is a floor because positives are noisy.
3. **Why did the agent score 0% on positives at first, and what was the fix?** Judgment paragraph numbers can be negative (front matter), and the model read `[para -2]` as a dash and asked for paragraph 2. A tool hint and a prompt line fixed it: 0% became 66.7% on dev and 75% on test. The cause was in our data format, not the model's reluctance.
4. **What does the leaderboard show and what are its limits?** On 20 items per kind, plain LLMs asked "is this quote accurate?" accepted 5 to 35 of 100 altered quotes (deepseek-chat 5, gemini-3.1-flash-lite 35), while Pramaan with no AI accepted 0. Limits: small sample, one prompt, and rows under 90% usable answers are marked "not comparable". gemma-4-26b-a4b-it returned no usable answers and I did not find out why.
5. **Why an MCP server, and what does it not do?** It lets other assistants call `verify_citations` and `verify_quote` over the same checker, with AI off, so the server never spends money and never gives a tick the checker would not. It is an optional extra, capped at 60,000 characters and 100 citations per call.

## Real reported fabrications: five likely questions
1. **Where did the items come from?** Public orders and named press reports: the Supreme Court's order of 27 Feb 2026 in Gummadi Usha Rani v. Sure Mallikarjuna Rao names four decisions a trial court relied on, and a Delhi High Court matter (Sept 2025) is reported by LiveLaw. Every item carries its source URL.
2. **Why only six?** Most reports say "non-existent judgments" without naming them, and the two press summaries of the six Pooja Ramesh Singh citations disagree. I left out anything I could not tie to a named source rather than guess.
3. **Is "0 of 5 marked VERIFIED" a good result?** It is the minimum bar, not an accuracy figure. It shows the deterministic rule does not accept these strings. It does not show it can tell a fake from a real case missing from the corpus, and by design it does not try: the status is NOT_FOUND_IN_CORPUS.
4. **What did it miss?** The invented paragraph pinpoint on Raj Narain. The case is real, so VERIFIED for the case is right, but "paragraphs 73 and 74" are never tested because the paragraph check only runs with a quote. A "highest paragraph" rule is unsafe here: the database holds numbered paragraphs only up to 6 for that judgment.
5. **How would you extend it?** Add items only with a public source naming the citation; add a quote-based paragraph test when a draft gives a paragraph and a quote; and ask a lawyer to confirm each Supreme Court item against a law report.
