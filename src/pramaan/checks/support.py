"""Does the resolved judgment support the proposition it is cited for? (M5, SPEC 4.7)

Steps:
1. retrieve: rank the paragraphs of ONE judgment against the proposition (BM25), keep the top k;
2. judge: an LLM reads the proposition and those paragraphs and answers in strict JSON;
3. verify: the JSON must validate, and every evidence quote must really occur in the paragraph it
   names. On any failure we ask once more, telling the model what was wrong; then we give up
   and report cannot_determine. A judge that cannot show its evidence is never believed.
"""

import json
import math
import re
import sqlite3
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ValidationError

from pramaan.checks.quotes import load_paragraphs, normalise
from pramaan.llm.client import Backend, complete
from pramaan.llm.prompts import SUPPORT_SYSTEM, retry_suffix, support_user_prompt

TOP_K = 5
MAX_PARA_CHARS = 3000  # some "paragraphs" are millions of characters; the judge sees the start only
BM25_K1 = 1.5
BM25_B = 0.75
_WORD = re.compile(r"\w+")
# Words that carry no topic. Without this, "the" and "of" decide the ranking.
STOPWORDS = frozenset(
    "a an the of to in on at by for with and or nor is are was were be been being it its this that "
    "these those as from not no under any such which who whom has have had court held case".split()
)

Verdict = Literal[
    "supported", "partially_supported", "not_supported", "contradicted", "cannot_determine"
]


class Evidence(BaseModel):
    para_no: int
    quote: str


class JudgeAnswer(BaseModel):
    """The strict shape the judge must return."""

    verdict: Verdict
    evidence: list[Evidence] = []
    reason: str


class SupportResult(BaseModel):
    verdict: Verdict
    evidence: list[Evidence] = []
    reason: str
    attempts: int  # 0 = no model call was possible (nothing to read)
    paragraphs_given: list[int] = []
    cost_usd: float = 0.0
    latency_s: float = 0.0
    failure: str | None = None  # why we fell back to cannot_determine, if we did


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


def rank_paragraphs(
    paragraphs: list[tuple[int, str]], proposition: str, k: int = TOP_K
) -> list[tuple[int, str]]:
    """BM25 over one judgment's paragraphs. Returns up to k (para_no, text), best first.

    Paragraphs with no word in common with the proposition are dropped, never padded in.
    """
    query = set(_tokens(proposition))
    docs = [Counter(_tokens(text[:MAX_PARA_CHARS])) for _, text in paragraphs]
    n = len(docs)
    if not query or n == 0:
        return []
    avg_len = sum(sum(d.values()) for d in docs) / n or 1.0
    df = {t: sum(1 for d in docs if t in d) for t in query}
    scored = []
    for (para_no, text), d in zip(paragraphs, docs, strict=True):
        length = sum(d.values())
        score = 0.0
        for t in query:
            tf = d.get(t, 0)
            if tf == 0:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            norm = tf + BM25_K1 * (1 - BM25_B + BM25_B * length / avg_len)
            score += idf * tf * (BM25_K1 + 1) / norm
        if score > 0:
            scored.append((score, para_no, text))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [(p, t[:MAX_PARA_CHARS]) for _, p, t in scored[:k]]


def parse_answer(raw: str) -> JudgeAnswer:
    """Pull the JSON object out of the reply (models sometimes add fences) and validate it."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in the reply")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
    try:
        return JudgeAnswer.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"JSON does not match the required shape: {e.errors()[0]['msg']}") from e


def verify_answer(answer: JudgeAnswer, given: list[tuple[int, str]]) -> str | None:
    """Return a description of the first problem, or None if the answer is acceptable."""
    by_para = {n: normalise(text) for n, text in given}
    needs_evidence = answer.verdict in ("supported", "partially_supported", "contradicted")
    if needs_evidence and not answer.evidence:
        return f"verdict {answer.verdict} needs at least one evidence quote"
    for ev in answer.evidence:
        if ev.para_no not in by_para:
            return f"para_no {ev.para_no} was not among the paragraphs given"
        quote = normalise(ev.quote)
        if not quote:
            return f"empty quote for para {ev.para_no}"
        if quote not in by_para[ev.para_no]:
            return f"quote not found word for word in para {ev.para_no}: '{ev.quote[:80]}'"
    return None


def judge_support(
    proposition: str,
    given: list[tuple[int, str]],
    *,
    model: str | None = None,
    backend: Backend | None = None,
    **client_kw,
) -> SupportResult:
    """Ask the judge (at most twice) about the supplied paragraphs. Never raises on bad output."""
    if not given:
        return SupportResult(
            verdict="cannot_determine",
            reason="No paragraph of the judgment shares a topic word with the proposition.",
            attempts=0,
        )
    base_prompt = support_user_prompt(proposition, given)
    prompt, problem = base_prompt, ""
    cost = latency = 0.0
    paras = [n for n, _ in given]
    for attempt in (1, 2):
        reply = complete(
            prompt, SUPPORT_SYSTEM, model=model, purpose="support_judge",
            backend=backend, **client_kw,
        )
        cost += reply.cost_usd
        latency += reply.latency_s
        try:
            answer = parse_answer(reply.text)
            problem = verify_answer(answer, given) or ""
        except ValueError as e:
            problem = str(e)
        if not problem:
            return SupportResult(
                verdict=answer.verdict, evidence=answer.evidence, reason=answer.reason,
                attempts=attempt, paragraphs_given=paras, cost_usd=cost, latency_s=latency,
            )
        prompt = base_prompt + retry_suffix(problem)
    return SupportResult(
        verdict="cannot_determine",
        reason="The judge did not return a valid, verifiable answer.",
        attempts=2, paragraphs_given=paras, cost_usd=cost, latency_s=latency, failure=problem,
    )


def check_support(
    con: sqlite3.Connection,
    case_id: str,
    proposition: str,
    *,
    k: int = TOP_K,
    model: str | None = None,
    backend: Backend | None = None,
    **client_kw,
) -> SupportResult:
    given = rank_paragraphs(load_paragraphs(con, case_id), proposition, k)
    return judge_support(proposition, given, model=model, backend=backend, **client_kw)
