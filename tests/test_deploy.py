import gzip
import sqlite3

import pytest
from fastapi.testclient import TestClient

from pramaan.api.app import RATE_LIMIT, create_app
from pramaan.api.ratelimit import RateLimiter
from pramaan.data.fetch_db import ensure_database, sha256_of


def make_gz(tmp_path):
    plain = tmp_path / "src.db"
    con = sqlite3.connect(plain)
    con.execute("CREATE TABLE t (x)")
    con.commit()
    con.close()
    packed = tmp_path / "src.db.gz"
    packed.write_bytes(gzip.compress(plain.read_bytes()))
    return packed


def test_download_unpacks_and_is_skipped_when_present(tmp_path):
    packed = make_gz(tmp_path)
    target = tmp_path / "out" / "pramaan.db"
    url = packed.as_uri()  # file:// needs no network
    assert ensure_database(target, url, sha256_of(packed)) is True
    assert sqlite3.connect(target).execute("SELECT count(*) FROM t").fetchone() == (0,)
    packed.unlink()  # a second call must not need the file again
    assert ensure_database(target, url, "ignored") is True


def test_wrong_checksum_is_refused_and_leaves_no_database(tmp_path):
    packed = make_gz(tmp_path)
    target = tmp_path / "pramaan.db"
    with pytest.raises(RuntimeError, match="sha256"):
        ensure_database(target, packed.as_uri(), "0" * 64)
    assert not target.exists()


def test_missing_and_unconfigured_is_false_not_a_crash(tmp_path):
    assert ensure_database(tmp_path / "x.db", None, None) is False


def test_rate_limiter_window():
    now = [0.0]
    limiter = RateLimiter(2, 60.0, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")  # other clients are unaffected
    now[0] = 61.0
    assert limiter.allow("a")


def test_api_returns_429_after_the_limit(tmp_path):
    db = tmp_path / "t.db"
    sqlite3.connect(db).close()
    client = TestClient(create_app(db))
    codes = [
        client.post("/check", files={"draft": ("d.txt", b"nothing")}).status_code
        for _ in range(RATE_LIMIT + 1)
    ]
    assert codes[-1] == 429 and 429 not in codes[:-1]
