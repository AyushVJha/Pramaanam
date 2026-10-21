"""M0 data inspection (SPEC.md §3.2): is text extractable from the judgment PDFs, and are
paragraphs numbered? Samples 20 random PDFs from the downloaded 2023 English tar.

Run: uv run python scripts/inspect_pdfs.py
"""

import random
import re
import tarfile
from pathlib import Path

import fitz  # PyMuPDF

TAR_PATH = Path("data/tar/year=2023/english/english.tar")
SAMPLE_SIZE = 20

# Candidate paragraph-marker shapes to look for in the extracted text, roughest first.
PARA_MARKER_PATTERNS = {
    "leading_digit_dot_newline": re.compile(r"(?m)^\s*(\d{1,3})\.\s"),
    "bracketed_digit": re.compile(r"(?m)^\s*\[(\d{1,3})\]"),
}


def sample_members(tar: tarfile.TarFile, n: int) -> list[tarfile.TarInfo]:
    members = [m for m in tar.getmembers() if m.isfile() and m.name.lower().endswith(".pdf")]
    random.seed(0)
    return random.sample(members, min(n, len(members)))


def main() -> None:
    with tarfile.open(TAR_PATH) as tar:
        members = sample_members(tar, SAMPLE_SIZE)
        n_total = len(tar.getmembers())
        print(f"Sampled {len(members)} PDFs from {TAR_PATH} (tar has {n_total} entries)\n")

        for member in members:
            fh = tar.extractfile(member)
            if fh is None:
                print(f"{member.name}: COULD NOT EXTRACT (no file handle)")
                continue
            data = fh.read()
            print(f"--- {member.name} ({len(data) / 1024:.0f} KB) ---")
            try:
                doc = fitz.open(stream=data, filetype="pdf")
            except Exception as exc:  # noqa: BLE001 - want to report, not crash, on a bad PDF
                print(f"  OPEN FAILED: {exc}")
                continue

            full_text = "\n".join(page.get_text() for page in doc)
            n_pages = doc.page_count
            n_chars = len(full_text.strip())
            extractable = n_chars > 200  # a scanned-image-only PDF yields ~0 chars

            print(f"  pages: {n_pages}  chars_extracted: {n_chars}  extractable: {extractable}")

            if extractable:
                for name, pat in PARA_MARKER_PATTERNS.items():
                    matches = pat.findall(full_text)
                    print(f"  marker[{name}]: {len(matches)} matches, first 5: {matches[:5]}")
                # show a short excerpt so marker style is visible by eye
                excerpt = full_text.strip()[:300].replace("\n", " \\n ")
                print(f"  excerpt: {excerpt!r}")
            doc.close()
            print()


if __name__ == "__main__":
    main()
