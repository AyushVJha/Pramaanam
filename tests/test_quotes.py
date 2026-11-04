from pramaan.checks.quotes import check_quote_in_paragraphs, normalise, split_segments

P1 = (
    "The doctrine of legitimate expectation does not confer an absolute right on any person "
    "and a mere hope or wish cannot be treated as an expectation that the court will protect."
)
P2 = (
    "In our view the High Court was right in holding that the appellant had failed to "
    "establish any violation of Article 14 of the Constitution of India in the present case."
)
P3 = (
    "The respondent paid a sum of Rs. 5,00,000 to the appellant on 12 March 1998 towards the "
    "sale consideration and took possession of the property on the same day without objection."
)
PARAS = [(1, P1), (2, P2), (3, P3), (4, "Appeal dismissed with costs throughout in this matter.")]


def check(quote, paras=PARAS):
    return check_quote_in_paragraphs(paras, quote)


def test_exact_quote_is_verbatim_and_names_the_paragraph():
    r = check("a mere hope or wish cannot be treated as an expectation that the court will protect")
    assert (r.status, r.para_nos, r.similarity) == ("verbatim", [1], 1.0)


def test_quote_marks_case_and_punctuation_do_not_matter():
    r = check("“The Doctrine of Legitimate Expectation does not confer an absolute right”")
    assert r.status == "verbatim"


def test_one_word_changed_is_a_near_match_with_the_change_shown():
    r = check("the High Court was wrong in holding that the appellant had failed to establish any "
              "violation of Article 14")
    assert r.status == "near_match" and r.para_nos == [2]
    assert any("'wrong'" in c and "'right'" in c for c in r.changes)


def test_inserted_negation_is_flagged():
    r = check("The doctrine of legitimate expectation does not confer an absolute right on any "
              "person and a mere hope or wish cannot not be treated as an expectation")
    assert r.status == "near_match" and "negation" in r.flags


def test_removed_negation_is_flagged():
    r = check("The doctrine of legitimate expectation does confer an absolute right on any "
              "person and a mere hope or wish cannot be treated as an expectation")
    assert r.status == "near_match" and "negation" in r.flags


def test_changed_number_is_flagged():
    r = check("The respondent paid a sum of Rs. 5,00,000 to the appellant on 12 March 1999 "
              "towards the sale consideration and took possession of the property")
    assert r.status == "near_match" and "number" in r.flags


def test_invented_quote_is_not_found():
    r = check("The Court held that the sky is green and the appellant owned the moon entirely")
    assert r.status == "not_found" and r.para_nos == []


def test_quote_spliced_from_two_distant_paragraphs_is_not_verbatim():
    # first half from paragraph 1, second half from paragraph 3: they are not neighbours
    r = check("a mere hope or wish cannot be treated as an expectation that the court will "
              "protect took possession of the property on the same day without objection")
    assert r.status != "verbatim"


def test_quote_running_across_two_neighbouring_paragraphs_is_verbatim():
    r = check("any violation of Article 14 of the Constitution of India in the present case "
              "The respondent paid a sum of Rs. 5,00,000 to the appellant")
    assert r.status == "verbatim" and r.spans_paragraphs and r.para_nos == [2]


def test_ellipsis_checks_each_piece_separately():
    r = check("The doctrine of legitimate expectation does not confer an absolute right .... "
              "failed to establish any violation of Article 14 of the Constitution")
    # the two pieces come from different paragraphs, and both are real
    assert r.status == "verbatim" and r.para_nos == [1]


def test_an_ellipsis_with_one_invented_piece_is_not_found():
    r = check("The doctrine of legitimate expectation does not confer an absolute right .... "
              "the moon is made of green cheese and the appellant owns it entirely")
    assert r.status == "not_found"


def test_quote_in_two_paragraphs_lists_both():
    paras = [*PARAS, (5, P2)]
    assert check("establish any violation of Article 14 of the Constitution of India", paras
                 ).para_nos == [2, 5]


def test_very_short_quote_cannot_be_checked():
    assert check("the appellant").status == "too_short"


def test_normalise_and_split_helpers():
    assert normalise("“Hello,  World-wide”") == "hello world wide"
    assert split_segments("one two three four .... five six seven eight") == [
        "one two three four", "five six seven eight"
    ]


def test_sentences_from_one_paragraph_with_text_left_out_is_near_match_not_misquote():
    from pramaan.checks.quotes import check_quote_in_paragraphs

    para = (
        "A suit under this section is a suit of a special nature and presupposes a public trust. "
        "It can proceed only on an allegation of breach of trust or the need for directions "
        "from the court, and it must pray for the reliefs mentioned in the section. "
        "It is only when these conditions are fulfilled that the suit may be brought."
    )
    quote = (
        "A suit under this section is a suit of a special nature and presupposes a public trust. "
        "It is only when these conditions are fulfilled that the suit may be brought."
    )
    r = check_quote_in_paragraphs([(5, para)], quote)
    assert r.status == "near_match" and "omission" in r.flags
    invented = quote.split(". ")[0] + ". Costs shall follow the event in all such matters."
    assert check_quote_in_paragraphs([(5, para)], invented).status == "not_found"


def test_paragraph_numbers_inside_a_quote_are_ignored():
    from pramaan.checks.quotes import check_quote_in_paragraphs

    paras = [
        (9, "The State enjoys latitude in taxing statutes."),
        (10, "A taxing statute is not beyond challenge."),
    ]
    quote = (
        "9. The State enjoys latitude in taxing statutes. "
        "10. A taxing statute is not beyond challenge."
    )
    r = check_quote_in_paragraphs(paras, quote)
    assert r.status in ("verbatim", "near_match")


def test_two_dots_of_scan_debris_are_not_an_ellipsis():
    from pramaan.checks.quotes import check_quote_in_paragraphs

    text = "The ex-serviceman will get the benefit of such revision in respect of the pay scale."
    paras = [(1, text)]
    good = "The ex-serviceman will get the benefit of such revision"
    junk = good + " ·- . ,. . - - .. '.,. 955"
    assert check_quote_in_paragraphs(paras, good).status == "verbatim"
    assert check_quote_in_paragraphs(paras, junk).status != "verbatim"
    assert check_quote_in_paragraphs(paras, good + " .... in respect of the pay scale").status in (
        "verbatim", "near_match")
