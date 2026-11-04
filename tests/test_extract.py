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
