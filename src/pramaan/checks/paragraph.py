"""Check a cited paragraph ref against where the quote actually appears (+-1). (M4, SPEC 4.6)

Paragraph numbers in the corpus are the judgment's own numbers, so "para 23" in a draft is
paragraph 23 here.
"""

from typing import Literal

from pydantic import BaseModel

from pramaan.checks.quotes import QuoteResult


class ParagraphResult(BaseModel):
    status: Literal["correct", "adjacent", "wrong_paragraph", "cannot_check"]
    cited: int | None
    found: list[int] = []
    explanation: str


def check_paragraph(cited: int | None, quote: QuoteResult) -> ParagraphResult:
    """Compare the paragraph the draft cites with where the quote was found.

    "adjacent" (off by one) is kept apart from "correct" because an off-by-one is often a
    real quote with a slightly wrong pinpoint, which a reader can fix at a glance.
    """
    if cited is None:
        return ParagraphResult(
            status="cannot_check", cited=None, explanation="The draft cites no paragraph."
        )
    if quote.status not in ("verbatim", "near_match") or not quote.para_nos:
        return ParagraphResult(
            status="cannot_check", cited=cited,
            explanation="The quote was not found, so its paragraph cannot be compared.",
        )
    numbered = [n for n in quote.para_nos if n > 0]  # negative = text outside numbered paragraphs
    if not numbered:
        return ParagraphResult(
            status="cannot_check", cited=cited,
            explanation="The quote is in text that is not in a numbered paragraph (for example "
            "the opening of the judgment), so the paragraph number cannot be compared.",
        )
    quote = quote.model_copy(update={"para_nos": numbered})
    # A quote running across a break covers its paragraph and the next one.
    covered = {n + 1 for n in quote.para_nos} | set(quote.para_nos) if quote.spans_paragraphs \
        else set(quote.para_nos)
    found = quote.para_nos
    if cited in covered:
        return ParagraphResult(
            status="correct", cited=cited, found=found,
            explanation=f"The quote is in paragraph {cited}.",
        )
    if any(abs(cited - n) == 1 for n in covered):
        return ParagraphResult(
            status="adjacent", cited=cited, found=found,
            explanation=f"The draft cites paragraph {cited}, but the quote is in paragraph "
            f"{found[0]}, next to it.",
        )
    where = ", ".join(str(n) for n in found)
    return ParagraphResult(
        status="wrong_paragraph", cited=cited, found=found,
        explanation=f"The draft cites paragraph {cited}, but the quote is in paragraph {where}.",
    )
