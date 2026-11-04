"""OCR of one PDF page with the installed Tesseract command-line program.

This is used by the text-quality work (viewer pre-fill, engine comparison). The corpus text layer
does NOT come from here: it is the text already embedded in the PDFs.
"""

import subprocess
import tempfile
from pathlib import Path

import pymupdf

DPI = 300  # Tesseract reads small print better at 300 dpi than at screen resolution


def tesseract_text(page: pymupdf.Page, psm: int = 4) -> str:
    """OCR one page. `psm` is Tesseract's page segmentation mode: 3 auto, 4 column, 6 block."""
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "p.png"
        page.get_pixmap(dpi=DPI).save(png)
        subprocess.run(
            ["tesseract", str(png), str(Path(tmp) / "out"), "--psm", str(psm), "-l", "eng"],
            check=True, capture_output=True,
        )
        return (Path(tmp) / "out.txt").read_text(encoding="utf-8")
