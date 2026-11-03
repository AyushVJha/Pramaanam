from pramaan.llm.cache import cache_get, cache_key, cache_put


def test_key_ignores_param_order_but_not_values():
    a = cache_key("m", "s", "p", {"x": 1, "y": 2})
    assert a == cache_key("m", "s", "p", {"y": 2, "x": 1})
    assert a != cache_key("m", "s", "p", {"x": 1, "y": 3})


def test_key_changes_with_model_system_and_prompt():
    base = cache_key("m", "s", "p", {})
    assert base != cache_key("m2", "s", "p", {})
    assert base != cache_key("m", "s2", "p", {})
    assert base != cache_key("m", "s", "p2", {})


def test_put_then_get_round_trips(tmp_path):
    cache_put(tmp_path, "k", {"text": "हाँ", "n": 3})
    assert cache_get(tmp_path, "k") == {"text": "हाँ", "n": 3}


def test_miss_and_corrupt_file_are_none(tmp_path):
    assert cache_get(tmp_path, "nope") is None
    (tmp_path / "bad.json").write_text("{not json")
    assert cache_get(tmp_path, "bad") is None
