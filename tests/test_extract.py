from pramaan.citations.extract import extract


def test_each_quote_goes_to_its_own_citation_not_a_neighbour():
    text = (
        'A v. B, 2023 INSC 11: "first quoted sentence of the judgment".\n\n'
        'C v. D, 2023 INSC 12: "second quoted sentence of another judgment".\n\n'
        "E v. F, 2023 INSC 13, para 7."
    )
    got = [(c.raw, c.quoted_text, c.para_ref) for c in extract(text)]
    assert got == [
        ("2023 INSC 11", "first quoted sentence of the judgment", None),
        ("2023 INSC 12", "second quoted sentence of another judgment", None),
        ("2023 INSC 13", None, 7),
    ]


def test_sentence_words_in_front_of_a_name_are_trimmed_not_fatal():
    text = "The petitioner also relies on Maneka Gandhi v. Union of India, (1978) 1 SCC 999."
    assert extract(text)[0].case_name == "Maneka Gandhi v. Union of India"


def test_footnote_number_between_name_and_citation_makes_the_name_loose():
    text = "Banwarilal Agarawalla v. The State of Bihar and others15 13 (1978) 2 SCR 621"
    c = extract(text)[0]
    assert c.name_tight is False
    tight = extract("Maneka Gandhi v. Union of India, (1978) 1 SCC 248.")[0]
    assert tight.name_tight is True


def test_quote_far_from_its_citation_is_loose():
    far = 'He said "a long quoted sentence about statutes". ' + "Then more text. " * 8
    c = extract(far + "See Maneka Gandhi v. Union of India, (1978) 1 SCC 248.")[0]
    assert c.quoted_text and c.quote_tight is False


def test_narrative_between_two_quotations_is_not_a_quotation():
    # The closing mark of the first quote and the opening mark of the second must not pair up.
    text = (
        'He said "the first quoted passage is long enough" and then the Court went on to hold '
        'that interest is payable, see A v. B, (1978) 1 SCC 248, and later "a second quoted '
        'passage is here too".'
    )
    c = extract(text)[0]
    assert c.quoted_text is None or "went on to hold" not in c.quoted_text


def test_curly_and_straight_quotes_both_give_the_quoted_words():
    words = "These are the quoted words of the court"
    for q in (f"“{words}”", f'"{words}"'):
        c = extract(f"A v. B, (1978) 1 SCC 248: {q}.")[0]
        assert c.quoted_text == "These are the quoted words of the court"


def test_a_new_sentence_between_quote_and_citation_makes_the_link_loose():
    text = (
        'The Court said "interest is payable on the sum awarded". '
        "The point arose in A v. B, (1978) 1 SCC 248."
    )
    c = extract(text)[0]
    assert c.quoted_text and c.quote_tight is False
    tight = extract('See A v. B, (1978) 1 SCC 248: "interest is payable on the sum awarded".')[0]
    assert tight.quote_tight is True


def test_a_citation_inside_a_quotation_does_not_own_that_quotation():
    text = 'The Court observed "as held in A v. B, (1978) 1 SCC 248 that interest is payable".'
    assert extract(text)[0].quoted_text is None


def test_word_typed_drafts_nbsp_en_dash_and_single_curly_quotes():
    text = (
        "The Court held in Deepak Ananda Patil v. State of Maharashtra, 2023 INSC 11, "
        "at paras 12–14, ‘the second limb of the submission is that there are "
        "concurrent findings’. See also Maneka Gandhi v. Union of India, (1978) 1 SCC 248."
    )
    first, second = extract(text)
    assert first.case_name == "Deepak Ananda Patil v. State of Maharashtra"
    assert first.para_ref == 12
    assert first.quoted_text.startswith("the second limb")
    assert second.case_name == "Maneka Gandhi v. Union of India"


def test_court_apostrophe_is_not_a_closing_quote():
    text = "The Court’s view in A v. B, (1978) 1 SCC 248 was that the appeal fails."
    assert extract(text)[0].quoted_text is None


def test_lowercase_typed_names_are_left_alone():
    from pramaan.citations.extract import _clean_case_name

    assert _clean_case_name("ram prasad v. state of bihar") == "ram prasad v. state of bihar"
