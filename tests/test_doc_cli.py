import json
import zipfile

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
