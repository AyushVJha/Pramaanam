"""The permanent text layer: raw per-page text of every judgment, one Parquet file per year.

Why it exists: reading PDFs is the slow step of the corpus build. We read each PDF once,
store the raw PyMuPDF text per page, and rebuild everything else (cleaning, paragraphs, the
SQLite DB) from this much smaller file. Raw means uncleaned, so cleaning rules can change
without touching a PDF again. Pages are kept separate because page numbers matter for
pincite checks.

Layout: <DATA_DIR>/text/year=YYYY/pages.parquet with columns
    path (the PDF's name without "_EN.pdf", matches metadata `path`), page_no, text, extractor
"""

import logging
import tarfile
from pathlib import Path

import pandas as pd
import pymupdf

from pramaan.config import DATA_DIR
from pramaan.data.pdf_text import PageText, extract_raw_pages

logger = logging.getLogger(__name__)

EXTRACTOR = f"pymupdf-{pymupdf.version[0]}"
_PDF_SUFFIX = "_EN.pdf"


def text_layer_path(year: int, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "text" / f"year={year}" / "pages.parquet"


def build_text_layer(tar_path: Path, out_path: Path) -> int:
    """Read every PDF in `tar_path` once and write their raw page text to `out_path`.

    Returns the number of PDFs written. A PDF that fails to open is logged and skipped.
    """
    rows = []
    n_pdfs = 0
    with tarfile.open(tar_path) as tar:
        for member in tar:
            if not (member.isfile() and member.name.endswith(_PDF_SUFFIX)):
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            path = member.name.removesuffix(_PDF_SUFFIX)
            try:
                pages = extract_raw_pages(fh.read())
            except Exception:
                logger.warning("failed to extract %s", member.name, exc_info=True)
                continue
            n_pdfs += 1
            rows.extend((path, p.page_no, p.text, EXTRACTOR) for p in pages)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["path", "page_no", "text", "extractor"])
    tmp = out_path.with_suffix(".tmp")
    df.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(out_path)  # atomic: a crash never leaves a half-written file
    return n_pdfs


def load_raw_pages(year: int, data_dir: Path = DATA_DIR) -> dict[str, list[PageText]] | None:
    """Raw pages per PDF `path` for one year, or None if the text layer isn't built yet."""
    parquet = text_layer_path(year, data_dir)
    if not parquet.exists():
        return None
    df = pd.read_parquet(parquet)
    pages: dict[str, list[PageText]] = {}
    for row in df.sort_values(["path", "page_no"]).itertuples():
        pages.setdefault(row.path, []).append(PageText(page_no=row.page_no, text=row.text))
    return pages
