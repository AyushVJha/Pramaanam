import tarfile
from pathlib import Path

from pramaan.data.pdf_text import extract_raw_pages
from pramaan.data.text_layer import build_text_layer, load_raw_pages

FIXTURES = Path(__file__).parent / "fixtures" / "pdfs"


def _make_tar(tmp_path: Path) -> Path:
    tar_path = tmp_path / "english.tar"
    with tarfile.open(tar_path, "w") as tar:
        for pdf in sorted(FIXTURES.glob("*_EN.pdf"))[:2]:
            tar.add(pdf, arcname=pdf.name)
    return tar_path


def test_text_layer_roundtrip_matches_direct_extraction(tmp_path):
    tar_path = _make_tar(tmp_path)
    out = tmp_path / "text" / "year=2023" / "pages.parquet"

    n = build_text_layer(tar_path, out)

    assert n == 2
    assert out.exists() and not out.with_suffix(".tmp").exists()
    pages = load_raw_pages(2023, data_dir=tmp_path)
    assert pages is not None
    for pdf in sorted(FIXTURES.glob("*_EN.pdf"))[:2]:
        key = pdf.name.removesuffix("_EN.pdf")
        assert pages[key] == extract_raw_pages(pdf.read_bytes())


def test_load_raw_pages_is_none_when_not_built(tmp_path):
    assert load_raw_pages(1999, data_dir=tmp_path) is None
