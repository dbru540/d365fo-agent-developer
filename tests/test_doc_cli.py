import json
import zipfile

import pytest

from d365fo_agent.cli import main

WORD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Vendor</w:t></w:r></w:p>
    <w:p><w:r><w:t>Vendor invoice posting.</w:t></w:r></w:p>
  </w:body>
</w:document>"""


def test_build_doc_index_cli(tmp_path, capsys):
    internal = tmp_path / "internal"
    internal.mkdir()
    with zipfile.ZipFile(internal / "v.docx", "w") as zf:
        zf.writestr("word/document.xml", WORD_XML)
    mslearn = tmp_path / "ml"
    (mslearn / "finance").mkdir(parents=True)
    (mslearn / "finance" / "x.md").write_text("# X\n\nSome finance doc.\n", encoding="utf-8")
    db = tmp_path / "docs.db"

    rc = main([
        "build-doc-index", "--db", str(db),
        "--internal", str(internal), "--mslearn", str(mslearn),
        "--mslearn-base-url", "https://learn.microsoft.com/x", "--rebuild",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["chunks_added"] >= 2
    assert out["by_origin"].get("internal", 0) >= 1
    assert out["by_origin"].get("mslearn", 0) >= 1
    assert db.exists()


# ---------------------------------------------------------------------------
# Task 5a: --embed flag
# ---------------------------------------------------------------------------
WORD_XML_EMBED = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body>"
    "<w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr><w:r><w:t>X</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Some text here.</w:t></w:r></w:p>"
    "</w:body></w:document>"
)


def test_build_doc_index_embed_flag_degrades_without_extra(tmp_path, capsys):
    """--embed with EMBED_AVAILABLE=False must warn but not crash; stats still valid."""
    internal = tmp_path / "internal"
    internal.mkdir()
    with zipfile.ZipFile(internal / "x.docx", "w") as z:
        z.writestr("word/document.xml", WORD_XML_EMBED)
    db = tmp_path / "docs.db"

    rc = main([
        "build-doc-index", "--db", str(db), "--internal", str(internal),
        "--embed",  # extra flag — must not crash even without fastembed
    ])
    # Always exits 0 — embed failure is non-fatal
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "chunks_added" in out


# ---------------------------------------------------------------------------
# Task 5b: fetch-doc-vectors
# ---------------------------------------------------------------------------
def _make_vector_db(path):
    import sqlite3
    import struct

    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE chunk_vectors (chunk_id INTEGER, model TEXT, dim INTEGER, vector BLOB)")
    blob = struct.pack("<3f", 1.0, 0.0, 0.0)
    con.execute("INSERT INTO chunk_vectors VALUES (1, 'intfloat/multilingual-e5-small', 3, ?)", (blob,))
    con.commit()
    con.close()


def _fake_opener(asset_db_path):
    def opener(url):
        return open(asset_db_path, "rb")
    return opener


def test_fetch_doc_vectors_merges_into_existing_db(tmp_path):
    from d365fo_agent.cli import main  # noqa: F401  (ensures CLI importable)
    from d365fo_agent.doc_store import DocIndex
    from d365fo_agent.doc_ingest import Chunk
    from d365fo_agent.doc_vectors import fetch_doc_vectors

    docs_db = tmp_path / "docs.db"
    with DocIndex(docs_db) as di:
        di.add_chunks([Chunk("d", "mslearn", "d365fo", "ap", "T", "https://x", 0, "T\nsome text")])
    asset_db = tmp_path / "vectors.db"
    _make_vector_db(asset_db)
    result = fetch_doc_vectors(url="https://example.com/vectors.db", dest_db=docs_db,
                               opener=_fake_opener(asset_db))
    assert result["ok"] is True
    assert result["vectors_merged"] == 1
    import sqlite3
    con = sqlite3.connect(str(docs_db))
    count = con.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
    con.close()
    assert count == 1


def test_fetch_doc_vectors_rejects_non_http_url(tmp_path):
    from d365fo_agent.doc_vectors import fetch_doc_vectors
    from d365fo_agent.doc_store import DocIndex
    docs_db = tmp_path / "docs.db"
    DocIndex(docs_db).close()
    result = fetch_doc_vectors(url="ftp://example.com/v.db", dest_db=docs_db)
    assert result["ok"] is False
    assert "http" in result["error"].lower()
