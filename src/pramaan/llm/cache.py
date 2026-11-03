"""Disk cache for LLM responses, keyed by a hash of (model, prompt, params). (M5)

One small JSON file per request. The same request is never paid for twice, and a
benchmark run can be repeated for free.
"""

import hashlib
import json
from pathlib import Path


def cache_key(model: str, system: str, prompt: str, params: dict) -> str:
    """Stable hash of everything that can change the answer (dict order does not matter)."""
    payload = json.dumps(
        {"model": model, "system": system, "prompt": prompt, "params": params},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_get(cache_dir: Path, key: str) -> dict | None:
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None  # a half-written file counts as a miss


def cache_put(cache_dir: Path, key: str, value: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic rename: a crash never leaves a broken cache file
