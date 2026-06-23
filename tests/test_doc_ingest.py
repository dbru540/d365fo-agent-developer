import io
import zipfile
from pathlib import Path

from d365fo_agent.doc_ingest import (
    Chunk,
    extract_docx_paragraphs,
    markdown_paragraphs,
    chunk_paragraphs,
)

WORD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Rapprochement</w:t></w:r></w:p>
    <w:p><w:r><w:t>Le rapprochement </w:t></w:r><w:r><w:t>bancaire.</w:t></w:r></w:p>
  </w:body>
</w:document>"""


def _make_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", WORD_XML)


def test_extract_docx_paragraphs_detects_heading_and_joins_runs(tmp_path):
    docx = tmp_path / "spec.docx"
    _make_docx(docx)
    paras = extract_docx_paragraphs(docx)
    assert paras == [("heading", "Rapprochement"), ("body", "Le rapprochement bancaire.")]


def test_markdown_paragraphs_splits_headings_and_bodies():
    md = "# Titre\n\nPremier para.\n\n## Sous\nDeuxieme para.\n"
    paras = markdown_paragraphs(md)
    assert paras == [
        ("heading", "Titre"),
        ("body", "Premier para."),
        ("heading", "Sous"),
        ("body", "Deuxieme para."),
    ]


def test_chunk_paragraphs_groups_body_under_latest_heading():
    paras = [("heading", "Titre"), ("body", "corps un"), ("body", "corps deux")]
    chunks = chunk_paragraphs(
        paras, doc_id="d1", origin="internal", platform="d365fo",
        module="ap", source_ref="C:/spec.docx",
    )
    assert len(chunks) == 1
    c = chunks[0]
    assert isinstance(c, Chunk)
    assert c.title == "Titre"
    assert c.doc_id == "d1" and c.origin == "internal" and c.module == "ap"
    assert "corps un" in c.text and "corps deux" in c.text
    assert c.text.startswith("Titre")


def test_chunk_paragraphs_splits_on_max_chars():
    big = "x" * 900
    paras = [("heading", "T"), ("body", big), ("body", big)]
    chunks = chunk_paragraphs(
        paras, doc_id="d", origin="internal", platform="d365fo",
        module="", source_ref="p", max_chars=1000,
    )
    assert len(chunks) == 2
    assert chunks[0].ord == 0 and chunks[1].ord == 1
