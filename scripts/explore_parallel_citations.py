"""Explore: can parallel citations inside judgments give an SCC/AIR -> case map? (read-only)

Judgments write "Name, (2001) 2 SCC 386 : [2001] 1 SCR 1". The SCR (or neutral) number finds the
case by exact lookup; the SCC / AIR number written next to it then points to the same case.
This script mines every such group and measures, WITHOUT changing the database:
- how many distinct SCC / AIR numbers it can map, and how many are contradictory;
- a held-out check: map built from the citing judgments in the 70% hash group, scored on groups
  from the other 30%. Truth for the held-out group is its own SCR/neutral anchor. Nothing is tuned.

Usage: uv run python scripts/explore_parallel_citations.py [max_cases]
"""

import hashlib
import sqlite3
import sys
import time
from collections import Counter, defaultdict

from pramaan.citations.extract import Citation, extract
from pramaan.resolve.resolver import lookup_exact

APPROX = {"SCC", "AIR"}  # SCC OnLine is a different, per-year numbering; skipped here
EXACT = {"SCR", "NEUTRAL"}
MAX_YEAR_GAP = 2
DEV_PERCENT = 30


def is_dev(citing_case: str) -> bool:
    return int(hashlib.sha256(citing_case.encode()).hexdigest(), 16) % 100 < DEV_PERCENT


def groups(text: str, cits: list[Citation]) -> list[list[Citation]]:
    """Citations separated only by whitespace or a colon belong to one case."""
    out: list[list[Citation]] = []
    for c in sorted((c for c in cits if c.format != "CASE_NAME"), key=lambda c: c.span):
        if out and text[out[-1][-1].span[1] : c.span[0]].strip(" \t\n:") == "":
            out[-1].append(c)
        else:
            out.append([c])
    return out


def key_of(c: Citation) -> tuple:
    p = c.parsed
    return (c.format, p.year, p.volume, p.page)


def main() -> None:
    max_cases = int(sys.argv[1]) if len(sys.argv) > 1 else None
    con = sqlite3.connect("file:pramaan.db?mode=ro", uri=True)
    cases = [r[0] for r in con.execute("SELECT cnr FROM cases ORDER BY cnr")]
    cases = cases[:max_cases] if max_cases else cases

    evidence = []  # (citing_case, scc_air_key, target_case)
    n_groups = 0
    t0 = time.time()
    for i, cnr in enumerate(cases):
        for (text,) in con.execute("SELECT text FROM paragraphs WHERE case_id = ?", (cnr,)):
            if "SCC" not in text and "AIR" not in text:
                continue
            for g in groups(text, extract(text)):
                anchors = [c for c in g if c.format in EXACT and c.parsed]
                tested = [c for c in g if c.format in APPROX and c.parsed]
                if len(anchors) != 1 or not tested:
                    continue
                hits = lookup_exact(con, anchors[0].parsed)
                if len(hits) != 1 or hits[0].case_id == cnr:
                    continue
                n_groups += 1
                for c in tested:
                    if abs(c.parsed.year - anchors[0].parsed.year) <= MAX_YEAR_GAP:
                        evidence.append((cnr, key_of(c), hits[0].case_id))
        if i % 2000 == 0:
            elapsed = time.time() - t0
            print(f"{i}/{len(cases)} cases, {len(evidence)} rows, {elapsed:.0f}s", flush=True)

    # --- whole-corpus map quality ---
    by_key = defaultdict(Counter)
    for _, key, target in evidence:
        by_key[key][target] += 1
    conflicted = [k for k, c in by_key.items() if len(c) > 1]
    multi = [k for k, c in by_key.items() if sum(c.values()) >= 2]
    agree = [k for k in multi if len(by_key[k]) == 1]
    print(f"\nclean anchored groups: {n_groups}; evidence rows: {len(evidence)}")
    print(f"distinct SCC/AIR numbers mapped: {len(by_key)}")
    print(f"  seen once: {len(by_key) - len(multi)}; seen 2+ times: {len(multi)}")
    share = 100 * len(agree) / max(len(multi), 1)
    print(f"  of the 2+ ones, all evidence agrees: {len(agree)} ({share:.1f}%)")
    print(f"  keys with conflicting targets: {len(conflicted)}")

    # --- held-out check: build from non-dev citing judgments, score on dev ---
    built = defaultdict(Counter)
    for citing, key, target in evidence:
        if not is_dev(citing):
            built[key][target] += 1
    hit = right = wrong = unique = 0
    for citing, key, truth in evidence:
        if not is_dev(citing):
            continue
        hit += 1
        c = built.get(key)
        if not c:
            continue
        unique += 1
        top, _ = c.most_common(1)[0]
        if len(c) > 1 and c.most_common(2)[0][1] == c.most_common(2)[1][1]:
            continue  # tie: would refuse
        right += top == truth
        wrong += top != truth
    print(f"\nheld-out (dev citing judgments): {hit} SCC/AIR citations with a known true case")
    share = 100 * unique / max(hit, 1)
    print(f"  found in the map built from the other judgments: {unique} ({share:.1f}%)")
    print(f"  of those answered: correct {right}, wrong {wrong} "
          f"(precision {100*right/max(right+wrong,1):.1f}%)")
    print(f"  => correct overall: {100*right/max(hit,1):.1f}% of held-out citations")


if __name__ == "__main__":
    main()
