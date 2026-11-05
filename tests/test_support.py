import json

from pramaan.checks.support import (
    Evidence,
    JudgeAnswer,
    judge_support,
    parse_answer,
    rank_paragraphs,
    verify_answer,
)
from pramaan.llm.client import RawReply

PARAS = [
    (1, "The appellant was a clerk in the municipal office."),
    (2, "Anticipatory bail may be granted where the court finds no prima facie case."),
    (3, "The statute of limitation bars a suit filed after three years."),
]


class Scripted:
    """Fake backend: returns the given replies in order and counts calls."""

    def __init__(self, *texts):
        self.texts, self.calls = list(texts), 0

    def create(self, **kw):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return RawReply(text=text, input_tokens=500, output_tokens=50)


def answer(verdict="supported", para=2, quote="Anticipatory bail may be granted"):
    ev = [{"para_no": para, "quote": quote}] if quote else []
    return json.dumps({"verdict": verdict, "evidence": ev, "reason": "r"})


def run(tmp_path, backend):
    return judge_support(
        "anticipatory bail can be granted", PARAS, backend=backend, model="claude-haiku-5-5",
        cache_dir=tmp_path / "c", usage_log=tmp_path / "u.jsonl",
    )


# --- retrieval ---
def test_ranking_puts_topic_paragraph_first_and_drops_unrelated():
    got = rank_paragraphs(PARAS, "bail granted anticipatory", k=5)
    assert got[0][0] == 2
    assert [n for n, _ in got] == [2]  # nothing else shares a word


def test_ranking_ignores_stopwords_and_empty_query():
    assert rank_paragraphs(PARAS, "the of and", k=5) == []


def test_ranking_is_deterministic_and_respects_k():
    paras = [(i, "bail order") for i in range(1, 10)]
    assert [n for n, _ in rank_paragraphs(paras, "bail", k=3)] == [1, 2, 3]


def test_huge_paragraph_is_cut():
    got = rank_paragraphs([(1, "bail " + "x " * 10_000)], "bail", k=1)
    assert len(got[0][1]) <= 3000


# --- parsing and verifying ---
def test_parse_accepts_fenced_json_and_rejects_junk():
    assert parse_answer("```json\n" + answer() + "\n```").verdict == "supported"
    for bad in ("no json here", "{broken", '{"verdict": "maybe", "reason": "r"}'):
        try:
            parse_answer(bad)
            raise AssertionError("should have failed")
        except ValueError:
            pass


def test_verify_checks_quote_exists_in_named_paragraph():
    ok = JudgeAnswer(verdict="supported", reason="r",
                     evidence=[{"para_no": 2, "quote": "anticipatory BAIL may be granted,"}])
    assert verify_answer(ok, PARAS) is None  # case and punctuation do not matter
    wrong = [Evidence(para_no=3, quote="Anticipatory bail")]
    wrong_para = ok.model_copy(update={"evidence": wrong})
    assert "not found" in verify_answer(wrong_para, PARAS)
    unknown = ok.model_copy(update={"evidence": [Evidence(para_no=99, quote="x")]})
    assert "not among" in verify_answer(unknown, PARAS)


def test_supported_without_evidence_is_rejected_but_not_supported_is_fine():
    assert verify_answer(JudgeAnswer(verdict="supported", reason="r"), PARAS)
    assert verify_answer(JudgeAnswer(verdict="not_supported", reason="r"), PARAS) is None


# --- the judge loop ---
def test_good_first_answer_uses_one_call(tmp_path):
    fake = Scripted(answer())
    r = run(tmp_path, fake)
    assert (r.verdict, r.attempts, fake.calls) == ("supported", 1, 1)
    assert r.cost_usd > 0 and r.failure is None


def test_invented_quote_is_retried_once_then_accepted_if_fixed(tmp_path):
    fake = Scripted(answer(quote="Bail is always available"), answer())
    r = run(tmp_path, fake)
    assert (r.verdict, r.attempts, fake.calls) == ("supported", 2, 2)


def test_two_bad_answers_become_cannot_determine(tmp_path):
    fake = Scripted(answer(quote="invented words"), "not json")
    r = run(tmp_path, fake)
    assert r.verdict == "cannot_determine" and r.attempts == 2 and fake.calls == 2
    assert r.failure


def test_no_paragraphs_means_no_model_call(tmp_path):
    fake = Scripted(answer())
    r = judge_support("x", [], backend=fake, cache_dir=tmp_path / "c", usage_log=tmp_path / "u")
    assert r.verdict == "cannot_determine" and r.attempts == 0 and fake.calls == 0


# --- evidence by pointer ---
def ptr(verdict="supported", paras=(2,)):
    return json.dumps({"verdict": verdict, "paras": list(paras), "reason": "r"})


def run_ptr(tmp_path, backend):
    from pramaan.checks.support import judge_support_pointer

    return judge_support_pointer(
        "anticipatory bail can be granted", PARAS, backend=backend, model="claude-haiku-5-5",
        cache_dir=tmp_path / "c", usage_log=tmp_path / "u.jsonl",
    )


def test_pointer_evidence_is_real_text_looked_up_by_code(tmp_path):
    r = run_ptr(tmp_path, Scripted(ptr()))
    assert r.verdict == "supported" and r.attempts == 1
    assert r.evidence[0].para_no == 2
    assert r.evidence[0].quote in PARAS[1][1]  # copied by code, so it cannot be wrong


def test_pointer_to_unknown_paragraph_retries_then_cannot_determine(tmp_path):
    r = run_ptr(tmp_path, Scripted(ptr(paras=(99,))))
    assert r.verdict == "cannot_determine" and r.attempts == 2 and "99" in r.failure


def test_pointer_supported_without_paras_is_rejected_then_fixed(tmp_path):
    r = run_ptr(tmp_path, Scripted(ptr(paras=()), ptr()))
    assert r.verdict == "supported" and r.attempts == 2


def test_pointer_not_supported_needs_no_paras(tmp_path):
    r = run_ptr(tmp_path, Scripted(ptr("not_supported", ())))
    assert r.verdict == "not_supported" and r.evidence == []
