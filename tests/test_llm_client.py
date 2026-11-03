import json

import pytest

from pramaan.llm.client import RawReply, complete, estimate_cost


class FakeBackend:
    def __init__(self, text="ok", inp=1000, out=200):
        self.calls = 0
        self.reply = RawReply(text=text, input_tokens=inp, output_tokens=out)

    def create(self, **kwargs):
        self.calls += 1
        return self.reply


def run(tmp_path, backend, prompt="p", **kw):
    return complete(
        prompt, "sys", model="claude-haiku-5-5", backend=backend,
        cache_dir=tmp_path / "cache", usage_log=tmp_path / "usage.jsonl", **kw,
    )


def test_cost_estimate_uses_config_prices():
    # 1M in at $0.10 + 1M out at $0.50
    assert estimate_cost("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.60)


def test_unknown_model_costs_zero():
    assert estimate_cost("some-future-model", 1000, 1000) == 0.0


def test_second_identical_call_is_served_from_cache(tmp_path):
    fake = FakeBackend()
    first = run(tmp_path, fake)
    second = run(tmp_path, fake)
    assert fake.calls == 1
    assert not first.cached and second.cached
    assert second.cost_usd == 0.0 and second.text == first.text


def test_different_prompt_is_a_new_call(tmp_path):
    fake = FakeBackend()
    run(tmp_path, fake, prompt="a")
    run(tmp_path, fake, prompt="b")
    assert fake.calls == 2


def test_every_call_is_logged_including_cache_hits(tmp_path):
    fake = FakeBackend()
    run(tmp_path, fake, purpose="test")
    run(tmp_path, fake, purpose="test")
    rows = [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert [r["cached"] for r in rows] == [False, True]
    assert rows[0]["cost_usd"] > 0 and rows[0]["purpose"] == "test"
