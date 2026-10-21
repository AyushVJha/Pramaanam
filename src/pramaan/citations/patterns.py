"""Compiled regex patterns, one per citation format. (SPEC.md Appendix A)

Formats: neutral (INSC), SCC, SCC OnLine, AIR, SCR, case-name.

Appendix A's shapes are kept, loosened slightly for punctuation/whitespace a hand-written
draft would plausibly use (e.g. optional periods in "S.C.R."/"SCR"). Verified against real
citation strings pulled from our own corpus — see tests/test_patterns.py.
"""

import re

NEUTRAL = re.compile(r"\b(?:19|20)\d{2}\s+INSC\s+\d{1,5}\b")

SCC = re.compile(r"\(\s*(?:19|20)\d{2}\s*\)\s*\d{1,2}\s+SCC\s+\d{1,4}\b")

SCC_ONLINE = re.compile(r"\b(?:19|20)\d{2}\s+SCC\s+OnLine\s+SC\s+\d{1,5}\b", re.IGNORECASE)

AIR = re.compile(r"\bAIR\s+(?:19|20)\d{2}\s+SC\s+\d{1,5}\b")

SCR = re.compile(
    r"[\[\(]\s*(?:19|20)\d{2}\s*[\]\)]\s*(?:\d{1,2}\s+)?(?:Supp\.?\s*)?(?:\(\d\)\s*)?"
    r"S\.?\s?C\.?\s?R\.?\s+\d{1,4}\b"
)

# High recall, low precision by design (SPEC.md Appendix A) — extract.py applies heuristic
# filtering; a full fix needs the LLM fallback SPEC.md §4 step 1 describes (deferred to M5+,
# since llm/client.py doesn't exist yet). Two fixes over the raw Appendix A shape, both
# found necessary against real text (see DECISIONS.md):
# - character class excludes digits/commas so the match doesn't run on into a following
#   "AIR 2005 SC 626"-style citation (Appendix A's \w and comma both included digits)
# - each side is capped at 8 words so it can't swallow a whole preceding clause like
#   "To cite a few judgments in this regard are Y.S. Jagan Mohan Reddy v. ..."
_NAME_PART = r"[A-Z][A-Za-z.&'\-]*(?:\s+[A-Za-z.&'\-]+){0,7}"
CASE_NAME = re.compile(rf"{_NAME_PART}\s+v(?:s)?\.?\s+{_NAME_PART}")

# Checked in priority order: more specific formats first, so a SCR match inside a longer
# string isn't mistaken for e.g. a bare neutral-citation-shaped substring.
STRUCTURED = {
    "SCR": SCR,
    "SCC_ONLINE": SCC_ONLINE,
    "SCC": SCC,
    "AIR": AIR,
    "NEUTRAL": NEUTRAL,
}
