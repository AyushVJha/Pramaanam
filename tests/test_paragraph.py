from pramaan.checks.paragraph import check_paragraph
from pramaan.checks.quotes import QuoteResult


def q(nos, status="verbatim", spans=False):
    return QuoteResult(status=status, similarity=1.0, para_nos=nos, spans_paragraphs=spans)


def test_cited_paragraph_matches():
    assert check_paragraph(23, q([23])).status == "correct"


def test_off_by_one_is_adjacent_both_ways():
    assert check_paragraph(22, q([23])).status == "adjacent"
    assert check_paragraph(24, q([23])).status == "adjacent"


def test_far_away_is_wrong_and_says_where():
    r = check_paragraph(5, q([23]))
    assert r.status == "wrong_paragraph" and "23" in r.explanation


def test_quote_in_several_paragraphs_matches_any():
    assert check_paragraph(40, q([23, 40])).status == "correct"


def test_quote_across_a_break_covers_both_paragraphs():
    assert check_paragraph(24, q([23], spans=True)).status == "correct"
    assert check_paragraph(25, q([23], spans=True)).status == "adjacent"


def test_no_paragraph_cited_cannot_be_checked():
    assert check_paragraph(None, q([23])).status == "cannot_check"


def test_missing_quote_cannot_be_compared():
    r = check_paragraph(23, QuoteResult(status="not_found", similarity=0.0))
    assert r.status == "cannot_check"


def test_near_match_still_gets_a_paragraph_check():
    assert check_paragraph(23, q([23], status="near_match")).status == "correct"
