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


def test_ollama_backend_sends_chat_request_and_reads_counts(monkeypatch):
    import io

    from pramaan.llm.client import OllamaBackend

    seen = {}

    def fake_urlopen(request, timeout, **kw):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        reply = {"message": {"content": '{"a": 1}'}, "prompt_eval_count": 12, "eval_count": 3}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = OllamaBackend("http://x:1").create(model="m", system="s", prompt="p", max_tokens=50)
    assert (out.text, out.input_tokens, out.output_tokens) == ('{"a": 1}', 12, 3)
    assert seen["url"] == "http://x:1/api/chat"
    assert seen["body"]["think"] is False
    assert seen["body"]["format"] == "json" and seen["body"]["options"]["temperature"] == 0


def test_ollama_down_gives_a_helpful_error(monkeypatch):
    from pramaan.llm.client import OllamaBackend

    def boom(request, timeout):
        raise ConnectionRefusedError()

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RuntimeError, match="ollama serve"):
        OllamaBackend().create(model="m", system="s", prompt="p", max_tokens=5)


def test_open_models_cost_nothing():
    assert estimate_cost("qwen2.5:7b-instruct", 5000, 500) == 0.0


def test_openai_compat_backend_builds_request_and_reads_usage(monkeypatch):
    import io

    from pramaan import config
    from pramaan.llm.client import OpenAICompatBackend

    monkeypatch.setattr(config, "OPENAI_PATH", "/v1/chat/completions")  # not the local .env
    seen = {}

    def fake_urlopen(request, timeout, **kw):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        reply = {"choices": [{"message": {"content": "{}"}}],
                 "usage": {"prompt_tokens": 7, "completion_tokens": 2}}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = OpenAICompatBackend("http://h:9/", "k").create(
        model="m", system="s", prompt="p", max_tokens=5
    )
    assert (out.text, out.input_tokens, out.output_tokens) == ("{}", 7, 2)
    assert seen["url"] == "http://h:9/v1/chat/completions" and seen["auth"] == "Bearer k"


def test_openai_backend_without_url_explains_itself(monkeypatch):
    from pramaan.llm.client import OpenAICompatBackend

    monkeypatch.setattr("pramaan.config.OPENAI_URL", "")
    with pytest.raises(RuntimeError, match="PRAMAAN_OPENAI_URL"):
        OpenAICompatBackend()


def test_openai_backend_retries_429_then_succeeds(monkeypatch):
    import io
    import urllib.error

    from pramaan.llm import client

    calls = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":3}}'

    def fake_urlopen(req, timeout, **kw):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError("u", 429, "slow down", {"Retry-After": "0"}, io.BytesIO())
        return Resp()

    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    b = client.OpenAICompatBackend(url="http://x", api_key="k")
    assert b.create(model="m", system="s", prompt="p", max_tokens=5).text == "ok"
    assert len(calls) == 3


def test_openai_backend_gives_up_on_401(monkeypatch):
    import io
    import urllib.error

    import pytest

    from pramaan.llm import client

    def fake_urlopen(req, timeout, **kw):
        raise urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO())

    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="401"):
        client.OpenAICompatBackend(url="http://x").create(model="m", system="s", prompt="p",
                                                         max_tokens=5)


def test_dotenv_is_read_but_never_overrides(tmp_path, monkeypatch):
    from pramaan import config

    env = tmp_path / ".env"
    env.write_text("# c\nPRAMAAN_T_A=1\nPRAMAAN_T_B='two'\nbad line\nPRAMAAN_T_C=keep\n")
    monkeypatch.setenv("PRAMAAN_T_C", "already")
    monkeypatch.delenv("PRAMAAN_T_A", raising=False)
    monkeypatch.delenv("PRAMAAN_T_B", raising=False)
    config._load_dotenv(env)
    import os

    assert (os.environ["PRAMAAN_T_A"], os.environ["PRAMAAN_T_B"]) == ("1", "two")
    assert os.environ["PRAMAAN_T_C"] == "already"
    for k in ("PRAMAAN_T_A", "PRAMAAN_T_B"):
        monkeypatch.delenv(k, raising=False)


def test_cache_false_never_touches_the_disk_cache(tmp_path):
    from pramaan.llm.client import RawReply, complete

    class B:
        calls = 0

        def create(self, **kw):
            B.calls += 1
            return RawReply(text="x", input_tokens=1, output_tokens=1)

    cache = tmp_path / "cache"
    for _ in range(2):
        complete("p", "s", model="m", backend=B(), cache_dir=cache, usage_log=tmp_path / "u",
                 cache=False)
    assert B.calls == 2 and not cache.exists()  # nothing written, nothing reused


def test_openai_backend_reports_an_empty_reply_instead_of_crashing(monkeypatch):
    import io

    import pytest

    from pramaan.llm import client

    reply = b'{"choices":[{"finish_reason":"function_call_filter: MALFORMED","message":{}}]}'
    monkeypatch.setattr(client.urllib.request, "urlopen",
                        lambda req, timeout, **kw: io.BytesIO(reply))
    with pytest.raises(RuntimeError, match="no text"):
        client.OpenAICompatBackend(url="http://x").create(model="m", system="s", prompt="p",
                                                         max_tokens=5)


def test_usage_log_has_no_reply_text_when_cache_is_off(tmp_path):
    import json

    from pramaan.llm.client import RawReply, complete

    class B:
        def create(self, **kw):
            return RawReply(text="SECRET DRAFT WORDS", input_tokens=3, output_tokens=2)

    log = tmp_path / "u.jsonl"
    complete("p", "s", model="m", backend=B(), cache_dir=tmp_path / "c", usage_log=log, cache=False)
    row = json.loads(log.read_text())
    assert "text" not in row and "SECRET" not in log.read_text()
    assert row["input_tokens"] == 3  # token counts are still kept
    complete("p", "s", model="m", backend=B(), cache_dir=tmp_path / "c2", usage_log=log)
    assert "SECRET DRAFT WORDS" in log.read_text()  # benchmarks keep the text
