"""Build docs/LEADERBOARD.md from bench/results/baseline_*.json. No number is typed by hand."""

import json
from pathlib import Path

ROWS = []
for f in sorted(Path("bench/results").glob("baseline_*.json")):
    d = json.loads(f.read_text())
    total = sum(sum(v.values()) for v in d["llm"].values())
    answered = total - sum(v.get("no_answer", 0) for v in d["llm"].values())
    ROWS.append((d["model"], d["altered_accepted"], d["real_accepted"], answered, total))

# fewest altered quotes accepted first, but a run with under 90% usable answers is listed last
ROWS.sort(key=lambda r: (r[3] / r[4] < 0.9, r[1]["llm"]))
lines = [
    "# Do AI models catch altered Indian Supreme Court quotes?",
    "",
    "Each model is asked, from memory and with no access to the judgment: \"is this quotation "
    "accurate, word for word?\" for 120 dev items (20 each of: real, one word changed, negation, "
    "number changed, two passages spliced, invented). Source: `bench/eval_baseline_llm.py`; "
    "table built by `bench/make_leaderboard.py`.",
    "",
    "| Model | Altered or invented quotes it accepted (of 100) | Real quotes it accepted (of 20) "
    "| Usable answers | Note |",
    "|---|---|---|---|---|",
]
for model, alt, real, answered, total in ROWS:
    note = "" if answered / total >= 0.9 else "fewer than 90% usable answers: not comparable"
    lines.append(f"| {model} | {alt['llm']} | {real['llm']} | {answered}/{total} | {note} |")
if ROWS:
    p = ROWS[0][1]
    lines.append(f"| **Pramaan (no AI)** | **{p['pramaan']}** | **{ROWS[0][2]['pramaan']}** "
                 "| 120/120 | deterministic; reads the judgment |")
lines += ["", "Not completed (free tier too slow or closed on our key): see "
          "`logs/leaderboard_incomplete.txt`. One run per model, dev items only, "
          "first 20 per kind."]
Path("docs/LEADERBOARD.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
