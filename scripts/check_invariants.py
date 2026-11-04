"""Run the database invariants and write/compare the corpus manifest.

Usage: uv run python scripts/check_invariants.py            # check, exit 1 if a hard one fails
       uv run python scripts/check_invariants.py --write    # also (re)write data/MANIFEST.json
"""

import argparse
import sqlite3
import sys

from pramaan.config import DB_PATH
from pramaan.data.invariants import build_manifest, run_invariants

DB = DB_PATH
MANIFEST = DB_PATH.parent / "MANIFEST.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    results = run_invariants(con)
    for r in results:
        print(f"{'ok  ' if r.ok else 'FAIL'} {r.kind:4} {r.violations:>8}  {r.name}")
    if args.write:
        MANIFEST.write_text(build_manifest(DB, con).model_dump_json(indent=1) + "\n")
        print(f"wrote {MANIFEST}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
