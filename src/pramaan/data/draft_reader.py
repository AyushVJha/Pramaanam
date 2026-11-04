"""Read a draft from disk as plain text: .txt / .md, .docx (Word) or .pdf with a text layer.

For .docx the text comes out in document order: paragraphs and table cells as they appear.
Footnotes and endnotes are read straight from the file's XML (python-docx does not expose them)
and appended after the body, since Indian drafts often keep their citations there.
Known limits: headers/footers and text boxes are NOT read, and tracked changes show the current
text. The CLI says so.
"""

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

SUPPORTED = {".txt", ".md", ".docx", ".pdf"}


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _notes_text(path: Path) -> list[str]:
    """Text of each real footnote / endnote. Ids -1 and 0 are Word's separator lines."""
    out: list[str] = []
    with zipfile.ZipFile(path) as z:
        for part, tag in (("word/footnotes.xml", "footnote"), ("word/endnotes.xml", "endnote")):
            if part not in z.namelist():
                continue
            root = ET.fromstring(z.read(part))
            for note in root.iter(f"{_W}{tag}"):
                if int(note.get(f"{_W}id", "0")) <= 0:
                    continue
                text = "".join(t.text or "" for t in note.iter(f"{_W}t"))
                if text.strip():
                    out.append(text)
    return out


MAX_PDF_PAGES = 300
MAX_UNZIPPED_BYTES = 50 * 1024 * 1024  # a 2 MB upload can hold gigabytes after unzipping


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        if sum(info.file_size for info in z.infolist()) > MAX_UNZIPPED_BYTES:
            raise ValueError("This Word file is too large once unpacked.")
    doc = Document(str(path))
    parts: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            parts.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                seen: set[int] = set()  # a merged cell appears once per column it spans
                for cell in row.cells:
                    if id(cell._tc) not in seen:
                        seen.add(id(cell._tc))
                        parts.append(cell.text)
    parts += _notes_text(path)
    return "\n\n".join(p for p in parts if p.strip())


def _pdf_text(path: Path) -> str:
    """Text of a PDF draft, one paragraph per text block. Scanned PDFs (no text layer) are refused:
    we do not OCR drafts, so reading them would silently check nothing."""
    import pymupdf

    parts: list[str] = []
    with pymupdf.open(path) as doc:
        if len(doc) > MAX_PDF_PAGES:
            raise ValueError(f"This PDF has more than {MAX_PDF_PAGES} pages; split the draft.")
        for page in doc:
            for block in page.get_text("blocks", sort=True):
                if block[6] == 0:  # 0 = text block, 1 = image
                    parts.append(" ".join(block[4].split()))
    text = "\n\n".join(p for p in parts if p)
    if not text.strip():
        raise ValueError("This PDF has no text layer (a scan?). Export it from Word or paste text.")
    return text


def read_draft(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_text(path)
    if suffix == ".docx":
        return _docx_text(path)
    if suffix in SUPPORTED:
        return path.read_text(encoding="utf-8")
    raise ValueError(f"Unsupported file type {suffix!r}. Use one of: {sorted(SUPPORTED)}")
