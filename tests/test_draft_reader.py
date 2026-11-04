import pytest
from docx import Document

from pramaan.citations.extract import extract
from pramaan.data.draft_reader import read_draft


def test_txt_is_read_as_is(tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("See 2020 INSC 5.", encoding="utf-8")
    assert read_draft(f) == "See 2020 INSC 5."


def test_docx_paragraphs_and_tables_in_document_order(tmp_path):
    doc = Document()
    doc.add_paragraph("First paragraph.")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Cell A"
    table.cell(0, 1).text = "Cell B"
    doc.add_paragraph("Last paragraph.")
    f = tmp_path / "d.docx"
    doc.save(str(f))
    text = read_draft(f)
    assert text.index("First") < text.index("Cell A") < text.index("Cell B") < text.index("Last")


def test_citation_inside_a_docx_table_is_found(tmp_path):
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Held in Ram Lal v. State of Bihar, 2020 INSC 5 that bail is a right."
    f = tmp_path / "d.docx"
    doc.save(str(f))
    assert any(c.raw == "2020 INSC 5" for c in extract(read_draft(f)))


def test_merged_cell_is_not_repeated(tmp_path):
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Merged once"
    f = tmp_path / "d.docx"
    doc.save(str(f))
    assert read_draft(f).count("Merged once") == 1


def test_unsupported_type_is_a_clear_error(tmp_path):
    f = tmp_path / "d.pdf"
    f.write_bytes(b"%PDF")
    with pytest.raises(ValueError, match="Unsupported"):
        read_draft(f)


def _add_footnotes(docx_path, notes_xml):
    import zipfile

    with zipfile.ZipFile(docx_path, "a") as z:
        z.writestr("word/footnotes.xml", notes_xml)


def test_footnote_citations_are_read_and_separators_skipped(tmp_path):
    doc = Document()
    doc.add_paragraph("Body text.")
    f = tmp_path / "d.docx"
    doc.save(str(f))
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    _add_footnotes(f, (
        f'<w:footnotes xmlns:w="{ns}">'
        '<w:footnote w:id="-1"><w:p><w:r><w:t>SEPARATOR</w:t></w:r></w:p></w:footnote>'
        '<w:footnote w:id="1"><w:p><w:r><w:t>Ram Lal v. State of Bihar, 2020 INSC 5</w:t></w:r>'
        "</w:p></w:footnote></w:footnotes>"
    ))
    text = read_draft(f)
    assert "SEPARATOR" not in text
    assert any(c.raw == "2020 INSC 5" for c in extract(text))
