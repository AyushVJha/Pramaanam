"""Baseline: a plain LLM asked "is this quote really in that judgment?", next to Pramaan. DEV ONLY.

The plain model gets what a lawyer would paste into a chat box: the case name, the citation number
and the quoted words. It has no access to the judgment (that is the point: it answers from memory).
Pramaan runs on the very same items with the AI check off. We count, per kind of quote:
  accepted  the tool called the quote accurate / VERIFIED
The number that matters is how many altered or invented quotes each one accepts.

Items: the first N of each kind from bench/data/quotes_dev.jsonl (fixed order, no random choice).
Usage: uv run python bench/eval_baseline_llm.py [--n 20] [--model gemma-4-31b-it]
(uses the .env endpoint; --model overrides the model; a JSON result goes to bench/results/)
"""

import argparse
import json
import logging
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from eval_pipeline_quotes import ALTERED, own_citation
from pydantic import BaseModel, ValidationError

from pramaan.citations.extract import Citation
from pramaan.config import JUDGE_MODEL
from pramaan.llm.client import OpenAICompatBackend, complete
from pramaan.pipeline import check_citation

logging.basicConfig(level=logging.WARNING)
KINDS = ["real", "one_word", "negation", "number", "splice", "invented"]
SYSTEM = (
    "You help a lawyer check a draft. Answer ONLY with JSON: "
    '{"verdict": "accurate" | "inaccurate" | "unsure"}.'
)


class Verdict(BaseModel):
    verdict: str


def make_backend(provider: str):
    """None means the endpoint in .env. DeepSeek needs PRAMAAN_DEEPSEEK_API_KEY (.env only)."""
    if provider == "default":
        return None
    key = os.environ.get("PRAMAAN_DEEPSEEK_API_KEY", "")
    if not key:
        raise SystemExit("Set PRAMAAN_DEEPSEEK_API_KEY in .env first.")
    return OpenAICompatBackend(
        "https://api.deepseek.com", key, timeout=120.0, path="/chat/completions"
    )


def ask(name: str, raw: str, quote: str, model: str, backend=None) -> str:
    prompt = (
        f"The draft says: in {name}, {raw}, the Supreme Court of India wrote:\n"
        f'"{quote}"\n\nIs this quotation accurate, word for word, as it appears in that judgment?'
    )
    try:
        text = complete(prompt, SYSTEM, model=model, purpose="baseline", max_tokens=100,
                        backend=backend).text
        v = Verdict.model_validate_json(text[text.index("{") : text.rindex("}") + 1]).verdict
    except (RuntimeError, ValueError, ValidationError):
        return "no_answer"
    return v if v in ("accurate", "inaccurate", "unsure") else "no_answer"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--model", default=JUDGE_MODEL)
    ap.add_argument("--provider", choices=["default", "deepseek"], default="default")
    args = ap.parse_args()
    n, model = args.n, args.model
    backend = make_backend(args.provider)
    lines = Path("bench/data/quotes_dev.jsonl").read_text().splitlines()
    rows = [json.loads(x) for x in lines if x]
    assert all(r["split"] == "dev" for r in rows), "dev only"
    con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
    llm: dict[str, Counter] = defaultdict(Counter)
    pra: dict[str, Counter] = defaultdict(Counter)
    taken: Counter = Counter()
    for it in rows:
        k = it["kind"]
        if k not in KINDS or taken[k] >= n:
            continue
        own = own_citation(con, it["case_id"])
        if own is None:
            continue
        taken[k] += 1
        raw, parsed = own
        title = con.execute("SELECT title FROM cases WHERE cnr = ?", (it["case_id"],)).fetchone()[0]
        name = title.replace(" versus ", " v. ")
        llm[k][ask(name, raw, it["quote"], model, backend)] += 1
        cit = Citation(raw=raw, span=(0, 0), format=parsed.reporter, parsed=parsed, case_name=name,
                       proposition="", quoted_text=it["quote"], para_ref=it["cited_para"])
        pra[k][check_citation(con, cit, use_llm=False).status] += 1
    print(f"model: {model}   items per kind: {dict(taken)}\n")
    print(f"{'kind':10} {'plain LLM says accurate':26} {'Pramaan VERIFIED'}")
    for k in KINDS:
        t = taken[k]
        said = f"{llm[k]['accurate']:>3}/{t:<3}  {dict(llm[k])!s:36}"
        print(f"{k:10} {said} {pra[k]['VERIFIED']}/{t}")
    bad_llm = sum(llm[k]["accurate"] for k in KINDS if k in ALTERED)
    bad_pra = sum(pra[k]["VERIFIED"] for k in KINDS if k in ALTERED)
    total = sum(taken[k] for k in KINDS if k in ALTERED)
    print(f"\naltered/invented quotes accepted: plain LLM {bad_llm}/{total}, "
          f"Pramaan {bad_pra}/{total}")
    result = {
        "model": model, "items_per_kind": dict(taken),
        "llm": {k: dict(llm[k]) for k in KINDS},
        "pramaan_verified": {k: pra[k]["VERIFIED"] for k in KINDS},
        "altered_accepted": {"llm": bad_llm, "pramaan": bad_pra, "of": total},
        "real_accepted": {"llm": llm["real"]["accurate"], "pramaan": pra["real"]["VERIFIED"],
                          "of": taken["real"]},
    }
    out = Path("bench/results")
    out.mkdir(exist_ok=True)
    safe = model.replace("/", "_").replace(":", "_")
    (out / f"baseline_{safe}.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()