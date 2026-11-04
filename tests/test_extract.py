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
