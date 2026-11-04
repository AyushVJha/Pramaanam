from pathlib import Path

import pytest

from pramaan.data.layout import Block, page_text, printed_page_number
from pramaan.data.layout_store import DoneRecord, finished, read_blocks, sha256_of, write_batch


def _block(page, idx, label="text", text="x", layer="body"):
    return Block(page=page, idx=idx, layer=layer, label=label, text=text,
                 x0=0.0, y0=0.0, x1=1.0, y1=1.0)


def _rec(path, pages=1, blocks=1):
    return DoneRecord(path=path, pages=pages, blocks=blocks, seconds=1.0, engine="e",
                      pdf_sha256=sha256_of(path.encode()), part="")


def test_page_text_keeps_reading_order_and_skips_furniture():
    blocks = [
        _block(1, 1, text="second"), _block(1, 0, text="first"),
        _block(1, 2, label="page_header", text="941", layer="furniture"),
        _block(2, 0, text="other page"),
    ]
    assert page_text(blocks, 1) == "first\nsecond"


def test_page_text_can_pick_block_types():
    blocks = [_block(1, 0, text="body"), _block(1, 1, label="footnote", text="5 supra")]
    assert page_text(blocks, 1, {"footnote"}) == "5 supra"


def test_printed_page_number_comes_from_the_running_head():
    blocks = [
        _block(3, 0, label="page_header", text="ANAND v. STATE", layer="furniture"),
        _block(3, 1, label="page_header", text="941", layer="furniture"),
    ]
    assert printed_page_number(blocks, 3) == 941
    assert printed_page_number(blocks, 4) is None


def test_store_round_trip_and_resume(tmp_path):
    a = [_block(1, 0, text="alpha"), _block(1, 1, text="beta"), _block(2, 0, text="gamma")]
    b = [_block(1, 0, text="delta")]
    write_batch(tmp_path, [(_rec("A", 2, 3), a), (_rec("B", 1, 1), b)], part_number=0)
    assert set(finished(tmp_path)) == {"A", "B"}
    assert [x.text for x in read_blocks(tmp_path, "A")] == ["alpha", "beta", "gamma"]
    assert [x.text for x in read_blocks(tmp_path, "B")] == ["delta"]
    assert read_blocks(tmp_path, "missing") == []


def test_a_done_line_without_its_blocks_file_does_not_count(tmp_path):
    write_batch(tmp_path, [(_rec("A"), [_block(1, 0)])], part_number=0)
    (tmp_path / "blocks-00000.parquet").unlink()
    assert finished(tmp_path) == {}


def test_a_half_written_done_line_is_ignored(tmp_path):
    write_batch(tmp_path, [(_rec("A"), [_block(1, 0)])], part_number=0)
    with open(tmp_path / "done.jsonl", "a") as fh:
        fh.write('{"path": "B", "pages": ')  # a crash in the middle of a line
    assert set(finished(tmp_path)) == {"A"}


def test_docling_conversion_on_one_real_page():
    pytest.importorskip("docling")
    from pramaan.data.layout import convert_pdf, make_converter

    fixture = Path(__file__).parent / "fixtures" / "layout_page.pdf"
    blocks = convert_pdf(make_converter(num_threads=1), fixture)
    text = page_text(blocks, 1)
    assert blocks and "attachment" in text.lower()
    assert all(b.x1 >= b.x0 and b.y1 >= b.y0 for b in blocks)
