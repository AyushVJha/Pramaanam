"""Build the small database a web host needs, and its checksum. (deploy)

The live app does not use the paragraph full-text index (retrieval is done in Python), so the
serving copy drops it. Output: dist/pramaan-serving.db.gz and dist/pramaan-serving.sha256.
Needs about 2x the database size in free disk while it runs. Read-only on pramaan.db.

Usage: uv run python scripts/build_serving_db.py [pramaan.db]
"""

import gzip
import shutil
import sqlite3
import sys
from pathlib import Path

from pramaan.data.fetch_db import sha256_of

source = Path(sys.argv[1] if len(sys.argv) > 1 else "pramaan.db")
out_dir = Path("dist")
out_dir.mkdir(exist_ok=True)
plain = out_dir / "pramaan-serving.db"
packed = out_dir / "pramaan-serving.db.gz"

shutil.copyfile(source, plain)
con = sqlite3.connect(plain)
con.execute("DROP TABLE IF EXISTS paragraphs_fts")
con.commit()
con.execute("VACUUM")  # give the freed pages back, otherwise the file stays the same size
con.close()

with plain.open("rb") as src, gzip.open(packed, "wb", compresslevel=6) as dst:
    shutil.copyfileobj(src, dst, 1024 * 1024)
plain.unlink()

digest = sha256_of(packed)
(out_dir / "pramaan-serving.sha256").write_text(digest + "\n")
print(f"{packed}: {packed.stat().st_size / 1048576:.0f} MB, sha256 {digest}")
