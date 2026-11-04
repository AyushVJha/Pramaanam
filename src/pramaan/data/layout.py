"""Layout layer: turn one judgment PDF into typed blocks (re-plan step 4).

The embedded text layer in the PDFs has two known faults: OCR errors, and side notes (the case
name printed in the margin) spliced into the middle of body sentences. Docling's layout model
finds the blocks on each page and gives them a type (text, footnote, table, page_header, ...);
a fresh full-page Tesseract read gives the characters. Measured on 39 blind pages
(docs/DATA_NOTES.md section 16): no page over 5% character error, against 3 for the embedded text.

Docling is an optional extra (`uv sync --extra layout`) so the web app does not carry it. Nothing
here is imported at app start; `make_converter` imports Docling lazily.
"""

import logging
import shutil
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Block(BaseModel):
    """One block on one page. `idx` is the reading order within the page (0 is first)."""

    page: int  # 1-indexed, position in the PDF (not the printed page number)
    idx: int
    layer: str  # "body", or "furniture" for running heads and page numbers
    label: str  # Docling's block type: text, footnote, table, page_header, section_header, ...
    text: str
    x0: float  # box in PDF points, origin at the top-left of the page
    y0: float
    x1: float
    y1: float


def engine_version() -> str:
    """Names the software that made the blocks. Stored with them, so rebuilds can be compared."""
    try:
        docling = version("docling")
    except PackageNotFoundError:
        docling = "not-installed"
    tess = "not-installed"
    if shutil.which("tesseract"):
        out = subprocess.run(["tesseract", "--version"], capture_output=True, text=True)
        first = (out.stdout or out.stderr).splitlines()[0].split()
        tess = first[1] if len(first) > 1 else "unknown"
    return f"docling-{docling}+tesseract-{tess}"


def make_converter(num_threads: int = 2) -> Any:
    """A Docling converter: layout model plus full-page Tesseract OCR (not the embedded text)."""
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    options.accelerator_options = AcceleratorOptions(device="cpu", num_threads=num_threads)
    options.do_ocr = True
    options.ocr_options = TesseractCliOcrOptions(force_full_page_ocr=True, lang=["eng"])
    pdf_option = PdfFormatOption(pipeline_options=options)
    return DocumentConverter(format_options={InputFormat.PDF: pdf_option})


def blocks_from_document(doc: Any) -> list[Block]:
    """Read every block of a converted Docling document, body and furniture, page by page."""
    from docling_core.types.doc.document import ContentLayer

    layers = {ContentLayer.BODY, ContentLayer.FURNITURE}
    counter: dict[int, int] = {}
    blocks = []
    for item, _level in doc.iterate_items(included_content_layers=layers):
        if not getattr(item, "prov", None):
            continue  # a grouping node with no position on a page
        prov = item.prov[0]
        text = getattr(item, "text", "") or ""
        if not text and item.label.value == "table":
            text = item.export_to_markdown(doc=doc)
        box = prov.bbox.to_top_left_origin(page_height=doc.pages[prov.page_no].size.height)
        idx = counter.get(prov.page_no, 0)
        counter[prov.page_no] = idx + 1
        blocks.append(
            Block(
                page=prov.page_no, idx=idx, layer=item.content_layer.value,
                label=item.label.value, text=text,
                x0=box.l, y0=box.t, x1=box.r, y1=box.b,
            )
        )
    return blocks


def convert_pdf(converter: Any, pdf: Path | str) -> list[Block]:
    return blocks_from_document(converter.convert(str(pdf)).document)


def page_text(blocks: list[Block], page: int, labels: set[str] | None = None) -> str:
    """The body text of one page in reading order, optionally only some block types."""
    chosen = [
        b for b in blocks
        if b.page == page and b.layer == "body" and (labels is None or b.label in labels)
    ]
    return "\n".join(b.text for b in sorted(chosen, key=lambda b: b.idx))


def printed_page_number(blocks: list[Block], page: int) -> int | None:
    """The page number printed in the running head or foot, if one is found there."""
    for b in sorted(blocks, key=lambda b: b.idx):
        if b.page == page and b.layer == "furniture" and b.text.strip().isdigit():
            return int(b.text.strip())
    return None
