"""Run Docling on the excerpt pages and save its text per page (exploratory).

Not a Pramaan dependency.
Docling is NOT in Pramaan's environment. Run this file with a Python that has docling installed:
    /path/to/venv/bin/python bench/docling_pages.py default|ocr
Modes:
    default : Docling's layout model over the text already embedded in the PDF.
    ocr     : same, but every page is re-read with Tesseract (full-page OCR) first.
Output: logs/docling_<mode>.json  {"<path>|<page>": {"text": ..., "seconds": ...}}
"""

import json
import sys
import time
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

ROOT = Path(__file__).resolve().parent.parent
mode = sys.argv[1]
opts = PdfPipelineOptions()
if mode == "ocr":
    opts.do_ocr = True
    opts.ocr_options = TesseractCliOcrOptions(force_full_page_ocr=True, lang=["eng"])
conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})

items = json.loads((ROOT / "bench/labels/claude_excerpts.json").read_text())["items"]
out = {}
for it in items:
    pdf = ROOT / "bench/data/ground_truth/pdfs" / f"{it['path']}_EN.pdf"
    t = time.time()
    result = conv.convert(str(pdf), page_range=(it["page"], it["page"]))
    out[f"{it['path']}|{it['page']}"] = {
        "text": result.document.export_to_markdown(),
        "seconds": round(time.time() - t, 1),
    }
    print(it["path"], it["page"], out[f"{it['path']}|{it['page']}"]["seconds"], flush=True)
(ROOT / "logs").mkdir(exist_ok=True)
(ROOT / f"logs/docling_{mode}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
