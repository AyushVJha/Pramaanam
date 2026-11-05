"""The one place Pramaan talks to an LLM. (M5, CLAUDE.md "LLM usage and cost")

complete() does three things around every call:
1. looks in the disk cache first (same model + prompt + params means no new charge);
2. calls a backend (the Anthropic SDK in real use, a fake in tests);
3. appends one line to logs/llm_usage.jsonl with tokens, estimated cost and latency.

The backend is passed in as a plain object so tests never touch the network, and the `anthropic`
package is imported only when a real call is made.
"""

import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from pramaan import config
from pramaan.llm.cache import cache_get, cache_key, cache_put

log = logging.getLogger(__name__)

RETRIES, BASE_WAIT, MAX_WAIT = 4, 5.0, 60.0  # free tiers rate-limit; wait 5, 10, 20 s (cap 60)


class RawReply(BaseModel):
    """What a backend returns: the text and the token counts the API reported."""

    text: str
    input_tokens: int
    output_tokens: int


class Backend(Protocol):
    def create(self, *, model: str, system: str, prompt: str, max_tokens: int) -> RawReply: ...


class LLMResult(BaseModel):
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float  # 0.0 for a cache hit: nothing was charged
    cached: bool
    latency_s: float


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Dollar estimate from config.PRICES_PER_MTOK. Unknown model -> 0.0 with a warning."""
    if not model.startswith("claude"):
        return 0.0  # open models run locally: no per-token charge
    prices = config.PRICES_PER_MTOK.get(model)
    if prices is None:
        log.warning("no price known for model %s; cost logged as 0", model)
        return 0.0
    in_price, out_price = prices
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


class AnthropicBackend:
    """Real calls through the official SDK. Imported lazily so the package is optional."""

    def __init__(self) -> None:
        try:
            import anthropic
        except ImportError as e:  # the user chose not to add the dependency yet
            raise RuntimeError(
                "The `anthropic` package is not installed. Add it with `uv add anthropic` "
                "and put ANTHROPIC_API_KEY in .env."
            ) from e
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY; SDK retries 429/5xx itself

    def create(self, *, model: str, system: str, prompt: str, max_tokens: int) -> RawReply:
        # No temperature (newer models reject it). Low effort: this is a short, bounded judgment.
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return RawReply(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


class OllamaBackend:
    """Open models served locally by Ollama (http://localhost:11434). Standard library only."""

    def __init__(self, url: str | None = None, timeout: float = 600.0) -> None:
        self._url = (url or config.OLLAMA_URL).rstrip("/") + "/api/chat"
        self._timeout = timeout

    def create(self, *, model: str, system: str, prompt: str, max_tokens: int) -> RawReply:
        body = {
            "model": model,
            "stream": False,
            "format": "json",  # makes the model emit valid JSON; we still validate it ourselves
            "think": False,  # models with a thinking mode (Qwen3) otherwise spend the budget on it
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            # temperature 0: the same input gives the same verdict. num_ctx must hold 5 paragraphs.
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": max_tokens},
        }
        request = urllib.request.Request(
            self._url, json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = json.loads(response.read())
        except OSError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self._url}. Start it with `ollama serve` "
                f"and pull the model with `ollama pull {model}`."
            ) from e
        return RawReply(
            text=data["message"]["content"],
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )


def _ssl_context() -> ssl.SSLContext:
    """HTTPS trust store. python.org builds on macOS ship without one; certifi has it."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class OpenAICompatBackend:
    """Any server speaking the OpenAI chat API (llama.cpp server, vLLM). Standard library only."""

    def __init__(
        self, url: str | None = None, api_key: str | None = None, timeout: float = 900.0
    ) -> None:
        base = (url or config.OPENAI_URL).rstrip("/")
        if not base:
            raise RuntimeError("Set PRAMAAN_OPENAI_URL (for example http://127.0.0.1:8080).")
        self._url = base + config.OPENAI_PATH
        self._key = api_key if api_key is not None else config.OPENAI_API_KEY
        self._timeout = timeout

    def _send(self, request: urllib.request.Request) -> dict:
        """POST with backoff on rate limits (429) and server errors (5xx): free tiers need it."""
        for attempt in range(1, RETRIES + 1):
            try:
                with urllib.request.urlopen(
                    request, timeout=self._timeout, context=_ssl_context()
                ) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == RETRIES:
                    detail = e.read()[:300].decode("utf-8", "replace") if e.fp else ""
                    msg = f"Model server returned HTTP {e.code} at {self._url}. {detail}"
                    raise RuntimeError(msg) from e
                wait = float(e.headers.get("Retry-After") or BASE_WAIT * 2 ** (attempt - 1))
                time.sleep(min(wait, MAX_WAIT))
            except OSError as e:
                raise RuntimeError(f"Could not reach the model server at {self._url}.") from e
        raise RuntimeError("unreachable")

    def create(self, *, model: str, system: str, prompt: str, max_tokens: int) -> RawReply:
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        request = urllib.request.Request(self._url, json.dumps(body).encode("utf-8"), headers)
        data = self._send(request)
        usage = data.get("usage", {})
        return RawReply(
            text=data["choices"][0]["message"]["content"] or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )


def make_backend() -> Backend:
    """The backend named in config. Created only when a call is not served from the cache."""
    if config.JUDGE_BACKEND == "anthropic":
        return AnthropicBackend()
    if config.JUDGE_BACKEND == "openai":
        return OpenAICompatBackend()
    return OllamaBackend()


def _log_usage(path: Path, result: LLMResult, purpose: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "purpose": purpose, **result.model_dump()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def complete(
    prompt: str,
    system: str = "",
    *,
    model: str | None = None,
    max_tokens: int = 2048,
    purpose: str = "unspecified",
    backend: Backend | None = None,
    cache_dir: Path | None = None,
    usage_log: Path | None = None,
) -> LLMResult:
    model = model or config.JUDGE_MODEL
    cache_dir = cache_dir if cache_dir is not None else config.LLM_CACHE_DIR
    usage_log = usage_log if usage_log is not None else config.LLM_USAGE_LOG

    key = cache_key(model, system, prompt, {"max_tokens": max_tokens})
    start = time.perf_counter()

    hit = cache_get(cache_dir, key)
    if hit is not None:
        result = LLMResult(
            text=hit["text"],
            model=model,
            input_tokens=hit["input_tokens"],
            output_tokens=hit["output_tokens"],
            cost_usd=0.0,
            cached=True,
            latency_s=time.perf_counter() - start,
        )
    else:
        backend = backend or make_backend()
        reply = backend.create(model=model, system=system, prompt=prompt, max_tokens=max_tokens)
        cache_put(cache_dir, key, reply.model_dump())
        result = LLMResult(
            text=reply.text,
            model=model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            cost_usd=estimate_cost(model, reply.input_tokens, reply.output_tokens),
            cached=False,
            latency_s=time.perf_counter() - start,
        )
    _log_usage(usage_log, result, purpose)
    return result
