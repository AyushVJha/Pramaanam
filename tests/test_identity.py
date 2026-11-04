from pramaan.checks.identity import compare_identity


def _c(name, year, pet="OM KUMAR AND ORS.", resp="UNION OF INDIA", decided=2000):
    return compare_identity(name, year, pet, resp, decided)


def test_same_case_matches():
    assert _c("Om Kumar v. Union of India", 2001).verdict == "match"


def test_year_may_lag_the_decision_by_up_to_two_years():
    assert _c("Om Kumar v. Union of India", 2002).verdict == "match"
    assert _c("Om Kumar v. Union of India", 2003).verdict == "year_mismatch"


def test_year_before_the_decision_is_a_mismatch():
    assert _c("Om Kumar v. Union of India", 1999).verdict == "year_mismatch"


def test_right_number_wrong_name_is_flagged():
    r = _c("Maneka Gandhi v. Union of India", 2000)
    assert r.verdict == "name_mismatch"
    assert "OM KUMAR" in r.explanation


def test_name_mismatch_wins_over_year():
    assert _c("Maneka Gandhi v. Union of India", 1990).verdict == "name_mismatch"


def test_no_name_checks_year_only():
    assert _c(None, 2001).verdict == "match"
    assert _c(None, 1990).verdict == "year_mismatch"


def test_nothing_to_compare():
    assert _c(None, None).verdict == "cannot_check"


def test_name_without_versus_is_not_judged_on_name():
    assert _c("Om Kumar", 2001).verdict == "match"


def test_initial_v_in_a_party_name_is_not_the_separator():
    from pramaan.resolve.names import split_parties

    assert split_parties("P. V. Sivarajan v. The Union of India") == (
        "P. V. Sivarajan", "The Union of India",
    )
    assert split_parties("Ram v. Shyam") == ("Ram", "Shyam")


def test_one_matching_party_is_not_a_full_match():
    from pramaan.checks.identity import compare_identity

    r = compare_identity("Raja Ram v. Union of India", 2014, "Bhule Ram", "Union of India", 2014)
    assert r.verdict == "name_partial"
    ok = compare_identity("Bhule Ram v. Union of India", 2014, "Bhule Ram", "Union of India", 2014)
    assert ok.verdict == "match"
