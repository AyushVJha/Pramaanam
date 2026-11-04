"""Run Docling + full-page Tesseract OCR on WHOLE judgments; save every block it finds.

(exploratory)

Not a Pramaan dependency: run with a Python that has docling installed:
    /path/to/venv/bin/python bench/docling_whole.py <case_path> [<case_path> ...]
Output per case: logs/docling_whole_<case_path>.json
    {"seconds": ..., "pages": N, "items": [{"page", "label", "text", "bbox"}, ...]}
`label` is Docling's own block type (text, section_header, footnote, table, page_header,
page_footer, list_item, ...), so we can see what it recognises and what it drops.
"""

import json
import sys
import time
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

ROOT = Path(__file__).resolve().parent.parent
opts = PdfPipelineOptions()
opts.do_ocr = True
opts.ocr_options = TesseractCliOcrOptions(force_full_page_ocr=True, lang=["eng"])
conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})

for case in sys.argv[1:]:
    pdf = ROOT / "bench/data/ground_truth/pdfs" / f"{case}_EN.pdf"
    t = time.time()
    result = conv.convert(str(pdf))
    items = []
    for item, _level in result.document.iterate_items():
        prov = item.prov[0] if getattr(item, "prov", None) else None
        text = getattr(item, "text", "") or ""
        if not text and item.label.value == "table":
            text = item.export_to_markdown(doc=result.document)
        items.append({
            "page": prov.page_no if prov else None,
            "label": item.label.value,
            "text": text,
            "bbox": [round(v, 1) for v in prov.bbox.as_tuple()] if prov else None,
        })
    n_pages = len(result.document.pages)
    out = {"seconds": round(time.time() - t, 1), "pages": n_pages, "items": items}
    (ROOT / "logs" / f"docling_whole_{case}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1)
    )
    print(case, out["pages"], "pages", out["seconds"], "s", len(items), "blocks", flush=True)
