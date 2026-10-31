import subprocess

import pytest

from pramaan.data import retry


def test_retries_then_succeeds(monkeypatch):
    results = iter([subprocess.CalledProcessError(1, "x"), None])
    waits = []

    def fake_run(cmd, check):
        r = next(results)
        if r:
            raise r

    monkeypatch.setattr(retry.subprocess, "run", fake_run)
    monkeypatch.setattr(retry.time, "sleep", waits.append)
    retry.run_with_retry(["x"], "demo")
    assert waits == [10.0]


def test_raises_after_all_attempts(monkeypatch):
    def always_fail(cmd, check):
        raise subprocess.CalledProcessError(1, "x")

    monkeypatch.setattr(retry.subprocess, "run", always_fail)
    monkeypatch.setattr(retry.time, "sleep", lambda s: None)
    with pytest.raises(subprocess.CalledProcessError):
        retry.run_with_retry(["x"], "demo", attempts=3)
