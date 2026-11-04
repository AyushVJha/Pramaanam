# Claim contract: what each status promises

A status is a claim. Each one lists what must be true and what it does NOT say.
The rule behind all of them: a green tick needs deterministic proof; AI can raise a flag, never give a tick.

| Status | Pramaan claims | Pramaan does NOT claim |
|---|---|---|
| VERIFIED | The citation number identifies a judgment (exact neutral/SCR number, or an SCC/AIR pair printed in at least 2 other judgments); party name and year agree; every quote is word-for-word in that judgment; any cited paragraph holds the quote. | That the judgment supports the legal argument. That the source text has no errors elsewhere. |
| NOT_FOUND_IN_CORPUS | No judgment in the open dataset matches. | That the case is fake. |
| NAME_MISMATCH / MISQUOTE / WRONG_PARAGRAPH | Asserted only when the case is proven by its number. Otherwise reported as NEEDS_REVIEW ("Possible ..."). | |
| UNSUPPORTED / CONTRADICTED | An AI second opinion, with evidence quotes checked to exist in the judgment, said so on a proven case. | That a lawyer would agree. |
| LOW_FIDELITY_SOURCE | The quote matches except for differences that look like scan noise. | That the quote is exact or wrong. |
| CANNOT_VERIFY | A check could not run. | Anything about the citation. |
| NEEDS_REVIEW | A person must look: ambiguous number, year mismatch, found by name or one witness only, near-match, partial support. | |

Support check is advisory: it can only downgrade a VERIFIED to a warning (UNSUPPORTED, CONTRADICTED, NEEDS_REVIEW), never create a VERIFIED.
