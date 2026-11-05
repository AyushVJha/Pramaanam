import itertools
import json
import sqlite3

import pytest
from pydantic import BaseModel

from pramaan.agents.guard import AGENT_MAY_CHANGE, AGENT_MAY_SET, allowed_change
from pramaan.agents.runtime import Budget, Tool, run_agent
from pramaan.llm.client import RawReply
from pramaan.pipeline import Status

TEXT = {1: "The appellant was a clerk.", 2: "Anticipatory bail may be granted in a fit case."}


class Scripted:
    """Fake backend: replies in order, repeating the last one; counts calls."""

    def __init__(self, *texts):
        self.texts, self.calls = list(texts), 0

    def create(self, **kw):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return RawReply(text=text, input_tokens=100, output_tokens=20)


class ReadArgs(BaseModel):
    n: int


class Answer(BaseModel):
    verdict: str
    para_no: int
    quote: str


def read(a: ReadArgs) -> str:
    return TEXT[a.n]  # KeyError for a missing paragraph on purpose: tools may fail


TOOLS = [Tool("read_paragraph", "Read paragraph n.", ReadArgs, read)]


def verify(answer: Answer) -> str | None:
    if answer.quote not in TEXT.get(answer.para_no, ""):
        return f"quote not found in para {answer.para_no}"
    return None


def call(n):
    return json.dumps({"action": "tool", "tool": "read_paragraph", "args": {"n": n}})


def finish(para=2, quote="Anticipatory bail may be granted"):
    return json.dumps({"action": "finish", "answer": {
        "verdict": "supported", "para_no": para, "quote": quote}})


_run = itertools.count()


def go(tmp_path, backend, **kw):
    n = next(_run)  # fresh cache per run: scripted replies are never served from an earlier run
    return run_agent(
        "Is bail supported?", system="You read judgments.", tools=TOOLS, answer_model=Answer,
        verify=verify, backend=backend, model="claude-haiku-5-5",
        cache_dir=tmp_path / f"c{n}", usage_log=tmp_path / "u", **kw,
    )


def test_tool_then_finish(tmp_path):
    out = go(tmp_path, Scripted(call(2), finish()))
    assert out.status == "finished" and out.answer.para_no == 2 and out.steps == 2
    kinds = [t.kind for t in out.trace]
    assert kinds == ["model", "tool", "model", "final"]
    assert "Anticipatory" in out.trace[1].text  # the tool result is in the trace


def test_evidence_that_is_not_in_the_text_is_corrected_once_then_rejected(tmp_path):
    bad = finish(quote="Bail is always available")
    out = go(tmp_path, Scripted(bad, bad))
    assert out.status == "invalid" and "quote not found" in out.problem and out.answer is None
    fixed = go(tmp_path, Scripted(bad, finish()))
    assert fixed.status == "finished"  # one correction turn is allowed


def test_answer_of_the_wrong_shape_is_rejected(tmp_path):
    odd = json.dumps({"action": "finish", "answer": {"verdict": "yes"}})
    out = go(tmp_path, Scripted(odd, odd))
    assert out.status == "invalid" and out.answer is None


def test_step_limit(tmp_path):
    out = go(tmp_path, Scripted(call(1), call(2), call(1)), budget=Budget(max_steps=2))
    assert out.status == "budget_exhausted" and out.steps == 2


def test_same_call_twice_is_a_loop(tmp_path):
    out = go(tmp_path, Scripted(call(1), call(1)))
    assert out.status == "loop"


def test_cost_budget_stops_the_run(tmp_path):
    # 100 input + 20 output tokens of claude-haiku-5-5 cost far more than $0.0000001
    out = go(tmp_path, Scripted(call(1), call(2), finish()), budget=Budget(max_cost_usd=1e-7))
    assert out.status == "budget_exhausted" and out.steps == 1  # stopped before a second call


def test_garbage_twice_in_a_row_stops_but_once_is_forgiven(tmp_path):
    assert go(tmp_path, Scripted("hello", "still not json")).status == "invalid"
    assert go(tmp_path, Scripted("hello", call(2), finish())).status == "finished"


def test_unknown_tool_and_bad_arguments_are_shown_to_the_model_not_run(tmp_path):
    unknown = json.dumps({"action": "tool", "tool": "delete_everything", "args": {}})
    badargs = json.dumps({"action": "tool", "tool": "read_paragraph", "args": {"n": "x"}})
    assert go(tmp_path, Scripted(unknown, unknown)).status == "invalid"
    assert go(tmp_path, Scripted(badargs, call(2), finish())).status == "finished"


def test_a_tool_that_raises_does_not_crash_the_run(tmp_path):
    out = go(tmp_path, Scripted(call(99), call(2), finish()))
    assert out.status == "finished"
    assert "ERROR: KeyError" in out.trace[1].text


def test_long_tool_output_is_cut(tmp_path):
    TEXT[3] = "x" * 5000
    try:
        out = go(tmp_path, Scripted(call(3), finish()), budget=Budget(max_observation_chars=100))
    finally:
        del TEXT[3]
    assert "[cut]" in out.trace[1].text and len(out.trace[1].text) < 400


def test_the_last_step_tells_the_model_to_finish(tmp_path):
    seen = []

    class Spy(Scripted):
        def create(self, **kw):
            seen.append(kw["prompt"])
            return super().create(**kw)

    go(tmp_path, Spy(call(1), call(2)), budget=Budget(max_steps=2))
    assert "LAST step" in seen[-1] and "LAST step" not in seen[0]


def test_a_read_only_database_cannot_be_written_by_a_tool(tmp_path):
    path = tmp_path / "t.db"
    rw = sqlite3.connect(path)
    rw.execute("CREATE TABLE cases (cnr TEXT)")
    rw.commit()
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO cases VALUES ('x')")


# ---- the guard: no agent can hand out a green tick ----

ALL = list(Status.__args__)


def test_no_agent_can_ever_set_verified():
    assert not any(allowed_change(cur, "VERIFIED") for cur in ALL if cur != "VERIFIED")


@pytest.mark.parametrize("current,proposed", list(itertools.product(ALL, ALL)))
def test_guard_matrix(current, proposed):
    ok = allowed_change(current, proposed)
    if proposed == current:
        assert ok
    elif proposed == "VERIFIED":
        assert not ok
    elif current in {"MISQUOTE", "NAME_MISMATCH", "WRONG_PARAGRAPH", "LOW_FIDELITY_SOURCE",
                     "UNSUPPORTED", "CONTRADICTED"}:
        assert not ok  # a status code already earned cannot be rewritten by a model
    else:
        assert ok == (proposed in AGENT_MAY_SET and current in AGENT_MAY_CHANGE)


def test_not_found_can_only_become_needs_review_or_more_careful():
    assert allowed_change("NOT_FOUND_IN_CORPUS", "NEEDS_REVIEW")
    assert not allowed_change("NOT_FOUND_IN_CORPUS", "VERIFIED")
