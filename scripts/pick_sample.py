"""Pick the ~60 judgments whose extracted text a human will verify. Seeded, so reruns agree.

Strata: decade (1950s..2020s, 8) x length (short <= 6 pages, medium 7-25, long > 25). The picker
also records two cheap layout signals from the text layer so the sample is not all clean pages:
  noise   = share of characters that are not letters, digits, spaces or common punctuation
  digit   = share of characters that are digits (tables and statutes push this up)
Within each decade we take cases spread across the three length bands and, inside a band, one
case from the cleanest and one from the noisiest half where possible.

Reads only the local text layer (data/text). Writes bench/data/ground_truth/sample.json.
Usage: uv run python scripts/pick_sample.py [--per-decade 8] [--seed 20261104]
"""

import argparse
import json
import random
import re

import pandas as pd

from pramaan.config import DATA_DIR

ODD = re.compile(r"[^A-Za-z0-9\s.,;:()'\"\-/&%\[\]]")
OUT = DATA_DIR.parent / "bench" / "data" / "ground_truth" / "sample.json"


def band(n_pages: int) -> str:
    return "short" if n_pages <= 6 else "medium" if n_pages <= 25 else "long"


def case_stats(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for path, g in df.groupby("path"):
        text = "".join(g["text"])
        n = max(len(text), 1)
        rows.append(
            {
                "path": path,
                "pages": len(g),
                "chars": n,
                "noise": round(len(ODD.findall(text)) / n, 4),
                "digit": round(sum(c.isdigit() for c in text) / n, 4),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-decade", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20261104)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    picked = []
    for decade in range(1950, 2030, 10):
        years = [
            y for y in range(decade, decade + 10)
            if (DATA_DIR / "text" / f"year={y}").exists()
        ]
        # one year file per decade at a time keeps memory small; sample 3 years per decade
        years = sorted(rng.sample(years, min(3, len(years))))
        frames = []
        for y in years:
            df = pd.read_parquet(DATA_DIR / "text" / f"year={y}" / "pages.parquet")
            s = case_stats(df)
            s["year"] = y
            frames.append(s)
        stats = pd.concat(frames, ignore_index=True)
        stats = stats[stats["chars"] > 500]  # empty or near-empty PDFs are a separate question
        stats["band"] = stats["pages"].map(band)
        want = ["short", "medium", "long"]
        chosen: list[dict] = []
        i = 0
        while len(chosen) < args.per_decade and i < 50:
            b = want[i % 3]
            pool = stats[(stats["band"] == b) & ~stats["path"].isin([c["path"] for c in chosen])]
            if not pool.empty:
                pool = pool.sort_values("noise")
                half = len(pool) // 2
                # alternate: cleanest half, noisiest half
                part = pool.iloc[:half] if (i // 3) % 2 == 0 else pool.iloc[half:]
                part = part if not part.empty else pool
                row = part.iloc[rng.randrange(len(part))]
                chosen.append({**row.to_dict(), "decade": decade})
            i += 1
        picked.extend(chosen)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"seed": args.seed, "cases": picked}, indent=1, default=int))
    print(f"picked {len(picked)} judgments -> {OUT}")
    out = pd.DataFrame(picked)
    print(out.groupby(["decade", "band"]).size().unstack(fill_value=0))
    print(f"noise range {out['noise'].min()} to {out['noise'].max()}; "
          f"digit range {out['digit'].min()} to {out['digit'].max()}")


if __name__ == "__main__":
    main()
