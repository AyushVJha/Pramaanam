"""Citation pattern tests.

All positive examples are real strings pulled from our own corpus DB (judgments citing
*other* cases in their own text — see DECISIONS.md for why SCC/AIR/SCC-OnLine show up here
despite M0 finding zero of them in the corpus's own `citation` metadata field: that field
only covers each judgment's citation of *itself*, not the citations *within* its text).
Negatives are realistic sentences that should NOT trigger a match.
"""

import pytest

from pramaan.citations.patterns import AIR, CASE_NAME, NEUTRAL, SCC, SCC_ONLINE, SCR

# fmt: off
REAL_SCR = [
    "[2023] 16 S.C.R. 872", "[2023] 15 S.C.R. 808", "[2023] 13 S.C.R. 420",
    "[2023] 5 S.C.R. 17", "[2023] 2 S.C.R. 224", "[2023] 12 S.C.R. 646",
]
REAL_SCC = [
    "(1952) 1 SCC 334", "(2009) 4 SCC 523", "(2015) 11 SCC 669",
    "(2013) 3 SCC 66", "(1979) 3 SCC 54", "(2014) 16 SCC 543",
]
REAL_SCC_ONLINE = [
    "1951 SCC OnLine SC 49", "2023 SCC OnLine SC 1087", "2022 SCC OnLine SC 1117",
    "2023 SCC OnLine SC 417", "2021 SCC OnLine SC 966", "2021 SCC OnLine SC 687",
]
REAL_AIR = [
    "AIR 1950 SC 124", "AIR 2008 SC 2936", "AIR 1972 SC 2319",
    "AIR 1967 SC 483", "AIR 1965 SC 1153", "AIR 1982 SC 710",
]
REAL_NEUTRAL = [
    "2023 INSC 1043", "2023 INSC 1047", "2003 INSC 409",
    "2010 INSC 246", "2022 INSC 523", "2019 INSC 881",
]
REAL_CASE_NAMES = [
    "Y.S. Jagan Mohan Reddy vs. Central Bureau of Investigation",
    "State of Bihar and Another vs. Amit Kumar alias Bachcha Rai",
    "K Sashidhar v Indian Overseas Bank",
    "RAMKRISHNA FORGINGS LTD v. RAVINDRA LOONKAR",
    "D. N. SINGH v. COMMISSIONER OF INCOME TAX",
]
# fmt: on

TRICKY_NEGATIVES = [
    "see para 1983 of the report",  # a bare 4-digit number, not any citation shape
    "Rule 2023 of the SCC Manual applies",  # "SCC" present but not "(YYYY) N SCC N"
    "the appellant was aged 2023 days",  # no reporter name at all
    "In the year 2023, the amendment was notified",  # bare year, no bracket+reporter
    "This Court in 2023 considered many such cases",  # "2023" + prose, no INSC/reporter
    "the versus relationship between the two claims was disputed",  # "versus" not "X v. Y"
    "AIR India flight SC 2023 was delayed",  # "AIR" present but not AIR-citation shape
    "(2023) saw a record number of filings",  # bare parenthetical year, no SCC/volume/page
]


@pytest.mark.parametrize("raw", REAL_SCR)
def test_scr_matches_real_strings(raw):
    assert SCR.search(raw) is not None


@pytest.mark.parametrize("raw", REAL_SCC)
def test_scc_matches_real_strings(raw):
    assert SCC.search(raw) is not None


@pytest.mark.parametrize("raw", REAL_SCC_ONLINE)
def test_scc_online_matches_real_strings(raw):
    assert SCC_ONLINE.search(raw) is not None


@pytest.mark.parametrize("raw", REAL_AIR)
def test_air_matches_real_strings(raw):
    assert AIR.search(raw) is not None


@pytest.mark.parametrize("raw", REAL_NEUTRAL)
def test_neutral_matches_real_strings(raw):
    assert NEUTRAL.search(raw) is not None


@pytest.mark.parametrize("raw", REAL_CASE_NAMES)
def test_case_name_matches_real_strings(raw):
    assert CASE_NAME.search(raw) is not None


@pytest.mark.parametrize("text", TRICKY_NEGATIVES)
def test_no_format_matches_tricky_negatives(text):
    assert SCR.search(text) is None
    assert SCC.search(text) is None
    assert SCC_ONLINE.search(text) is None
    assert AIR.search(text) is None
    assert NEUTRAL.search(text) is None


def test_scc_does_not_run_on_into_a_following_citation():
    """Regression for the bug fixed in DECISIONS.md: the original Appendix A case-name
    regex's \\w/comma character class let a match run from a party name straight through
    a following structured citation. SCC/AIR/SCR patterns don't have that class, but this
    locks in that a following citation's digits don't get absorbed either."""
    text = "Bhanu Kumar Jain vs. Archana Kumar, AIR 2005 SC 626 : (2005) 1 SCC 787"
    air_match = AIR.search(text)
    scc_match = SCC.search(text)
    assert air_match.group(0) == "AIR 2005 SC 626"
    assert scc_match.group(0) == "(2005) 1 SCC 787"


def test_suppl_with_an_l_is_a_supplement_citation():
    from pramaan.citations.extract import extract

    cits = [c for c in extract("[1976] Suppl. SCR 172 and [1976] Suppl. 1 SCR 172")
            if c.format == "SCR"]
    assert [(c.parsed.reporter, c.parsed.volume, c.parsed.page) for c in cits] == [
        ("SCR-SUPP", None, 172), ("SCR-SUPP", 1, 172)]
