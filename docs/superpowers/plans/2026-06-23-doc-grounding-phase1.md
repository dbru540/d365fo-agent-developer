# Doc Grounding (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a queryable documentation index (MS Learn markdown + internal `.docx`) with `search_docs`/`get_docs`/`docs_stats` MCP tools, so an agent can ground FUNCTIONAL claims in cited sources — not just AOT metadata.

**Architecture:** A separate SQLite **FTS5** index (`docs.db`), distinct from the AOT symbol index, mirroring the proven `index_store.py` + `guidance.py` patterns. Ingestion normalizes both sources to `(style, text)` paragraphs → `Chunk` objects → FTS5 rows with source citations. The schema pre-creates an (unused) `chunk_vectors` table so the Phase 2 semantic layer needs no migration. Doc tools degrade gracefully when no `docs.db` is configured (same contract as `get_sql_model`).

**Tech Stack:** Python 3.11+, standard library only (`sqlite3`+FTS5, `zipfile`, `xml.etree.ElementTree`, `re`, `argparse`), `pytest`.

**Out of scope (next plan):** embeddings / semantic rerank (`embed.py`, the `[semantic]` extra, the prebuilt vector asset, `fetch-doc-vectors`). This plan ships a complete FTS5 deliverable on its own.

---

## File Structure

- **Create** `src/d365fo_agent/doc_ingest.py` — `Chunk` dataclass + `.docx`/markdown extraction + chunking + ingestion drivers.
- **Create** `src/d365fo_agent/doc_store.py` — `DocIndex` (SQLite FTS5): schema, `add_chunks`, `search`, `get`, `stats`.
- **Modify** `src/d365fo_agent/mcp_server.py` — add `doc_db_path` config, `_doc_index_if_ready()`, three `@tool`s, `--doc-db` arg.
- **Modify** `src/d365fo_agent/cli.py` — add `build-doc-index` command + thread `--doc-db` into `serve-mcp`.
- **Modify** `pyproject.toml` — no new runtime deps (note only); confirm tests pass.
- **Create** `tests/test_doc_ingest.py`, `tests/test_doc_store.py`, `tests/test_doc_mcp_tools.py`, `tests/test_doc_cli.py`.

Run all tests with: `$env:PYTHONPATH='src'; pytest -q` (PowerShell) — POSIX: `PYTHONPATH=src pytest -q`.

---

## Task 1: Chunk model + extraction (`doc_ingest.py`)

**Files:**
- Create: `src/d365fo_agent/doc_ingest.py`
- Test: `tests/test_doc_ingest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_ingest.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_ingest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'd365fo_agent.doc_ingest'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/d365fo_agent/doc_ingest.py
"""Ingest D365 functional documentation into citeable chunks for the doc index.

Two sources, normalized to the same ``(style, text)`` paragraph stream then chunked:
* **MS Learn** — Markdown from the public MicrosoftDocs D365 F&O repo, cloned locally.
* **Internal specs** — Word ``.docx``. A ``.docx`` is a zip of XML, so we read
  ``word/document.xml`` and pull the ``<w:t>`` runs with the standard library — NO python-docx.

Standard library only (``zipfile``, ``xml.etree``, ``re``).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_VALID_PLATFORMS = {"d365fo", "ax2012", "both"}


@dataclass
class Chunk:
    doc_id: str       # stable id of the source document
    origin: str       # "mslearn" | "internal"
    platform: str     # "d365fo" | "ax2012" | "both"
    module: str       # functional module, e.g. "accounts-payable" ("" if unknown)
    title: str        # section heading (the chunk's local title)
    source_ref: str   # URL (mslearn) or file path (internal) — the citation
    ord: int          # chunk order within the document
    text: str         # indexed text (title line + body)

    def to_dict(self) -> dict:
        return asdict(self)


def _para_style(para: ElementTree.Element) -> str:
    ppr = para.find(f"{WORD_NS}pPr")
    if ppr is None:
        return "body"
    pstyle = ppr.find(f"{WORD_NS}pStyle")
    if pstyle is None:
        return "body"
    val = pstyle.get(f"{WORD_NS}val", "")
    return "heading" if val.lower().startswith("heading") else "body"


def extract_docx_paragraphs(path: str | Path) -> list[tuple[str, str]]:
    """``.docx`` -> ``[(style, text)]`` where style is 'heading' or 'body'. Stdlib only."""
    with zipfile.ZipFile(Path(path)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    root = ElementTree.fromstring(xml)
    out: list[tuple[str, str]] = []
    for para in root.iter(f"{WORD_NS}p"):
        text = "".join(node.text for node in para.iter(f"{WORD_NS}t") if node.text).strip()
        if text:
            out.append((_para_style(para), text))
    return out


def markdown_paragraphs(md: str) -> list[tuple[str, str]]:
    """Markdown -> ``[(style, text)]``. ATX headings become 'heading'; blank-line-separated
    runs of text become 'body' paragraphs."""
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        joined = " ".join(line.strip() for line in buf).strip()
        if joined:
            out.append(("body", joined))
        buf.clear()

    for line in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if m:
            flush()
            out.append(("heading", m.group(2).strip()))
        elif not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return out


def chunk_paragraphs(
    paragraphs: list[tuple[str, str]], *, doc_id: str, origin: str, platform: str,
    module: str, source_ref: str, max_chars: int = 1500,
) -> list[Chunk]:
    """Group body paragraphs under the most recent heading into ``Chunk``s; split a section
    that exceeds ``max_chars``. The chunk text is the title line followed by the body."""
    if platform not in _VALID_PLATFORMS:
        platform = "d365fo"
    chunks: list[Chunk] = []
    title = doc_id
    buf: list[str] = []
    ordn = 0

    def flush() -> None:
        nonlocal buf, ordn
        body = "\n".join(buf).strip()
        if body:
            text = f"{title}\n{body}" if title else body
            chunks.append(Chunk(doc_id, origin, platform, module, title, source_ref, ordn, text))
            ordn += 1
        buf = []

    for style, text in paragraphs:
        if style == "heading":
            flush()
            title = text
        else:
            buf.append(text)
            if sum(len(x) for x in buf) >= max_chars:
                flush()
    flush()
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_ingest.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/d365fo_agent/doc_ingest.py tests/test_doc_ingest.py
git commit -m "feat: doc ingestion — Chunk model, .docx + markdown extraction"
```

---

## Task 2: Ingestion drivers (`doc_ingest.py`)

**Files:**
- Modify: `src/d365fo_agent/doc_ingest.py`
- Test: `tests/test_doc_ingest.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_doc_ingest.py`)

```python
from d365fo_agent.doc_ingest import ingest_internal_dir, ingest_mslearn_dir


def test_ingest_internal_dir_walks_docx(tmp_path):
    _make_docx(tmp_path / "vendor.docx")
    chunks = list(ingest_internal_dir(tmp_path, platform="d365fo"))
    assert chunks, "expected at least one chunk from the .docx"
    assert all(c.origin == "internal" for c in chunks)
    assert all(str(tmp_path) in c.source_ref or "vendor.docx" in c.source_ref for c in chunks)
    assert any("bancaire" in c.text for c in chunks)


def test_ingest_mslearn_dir_builds_citation_url(tmp_path):
    (tmp_path / "finance").mkdir()
    (tmp_path / "finance" / "settle.md").write_text(
        "# Settlement\n\nHow settlement works.\n", encoding="utf-8"
    )
    chunks = list(ingest_mslearn_dir(tmp_path, base_url="https://learn.microsoft.com/x"))
    assert chunks
    c = chunks[0]
    assert c.origin == "mslearn"
    assert c.source_ref == "https://learn.microsoft.com/x/finance/settle"
    assert c.module == "finance"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_ingest.py -q`
Expected: FAIL — `ImportError: cannot import name 'ingest_internal_dir'`.

- [ ] **Step 3: Write minimal implementation** (append to `src/d365fo_agent/doc_ingest.py`)

```python
def ingest_docx_file(
    path: str | Path, *, origin: str = "internal", platform: str = "d365fo", module: str = "",
) -> list[Chunk]:
    path = Path(path)
    paras = extract_docx_paragraphs(path)
    return chunk_paragraphs(
        paras, doc_id=path.stem, origin=origin, platform=platform,
        module=module, source_ref=str(path),
    )


def ingest_markdown_file(
    path: str | Path, *, source_ref: str, origin: str = "mslearn", platform: str = "d365fo",
    module: str = "", doc_id: str | None = None,
) -> list[Chunk]:
    path = Path(path)
    paras = markdown_paragraphs(path.read_text(encoding="utf-8", errors="ignore"))
    return chunk_paragraphs(
        paras, doc_id=doc_id or path.stem, origin=origin, platform=platform,
        module=module, source_ref=source_ref,
    )


def ingest_internal_dir(directory: str | Path, *, platform: str = "d365fo") -> Iterator[Chunk]:
    """Every ``*.docx`` under ``directory`` (recursive). Module = the file's parent folder name."""
    directory = Path(directory)
    for path in sorted(directory.rglob("*.docx")):
        if path.name.startswith("~$"):  # Word lock files
            continue
        module = path.parent.name if path.parent != directory else ""
        yield from ingest_docx_file(path, platform=platform, module=module)


def ingest_mslearn_dir(
    directory: str | Path, *, base_url: str | None = None, platform: str = "d365fo",
) -> Iterator[Chunk]:
    """Every ``*.md`` under ``directory`` (recursive). The citation is ``base_url`` + the
    posix relative path without the ``.md`` suffix; module = the top relative folder."""
    directory = Path(directory)
    for path in sorted(directory.rglob("*.md")):
        rel = path.relative_to(directory).as_posix()
        slug = rel[:-3] if rel.endswith(".md") else rel
        source_ref = f"{base_url.rstrip('/')}/{slug}" if base_url else str(path)
        module = path.relative_to(directory).parts[0] if len(path.relative_to(directory).parts) > 1 else ""
        yield from ingest_markdown_file(
            path, source_ref=source_ref, platform=platform, module=module, doc_id=slug,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_ingest.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/d365fo_agent/doc_ingest.py tests/test_doc_ingest.py
git commit -m "feat: doc ingestion drivers for .docx folders and MS Learn markdown"
```

---

## Task 3: `DocIndex` store — schema, add, get, stats (`doc_store.py`)

**Files:**
- Create: `src/d365fo_agent/doc_store.py`
- Test: `tests/test_doc_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_store.py
from d365fo_agent.doc_ingest import Chunk
from d365fo_agent.doc_store import DocIndex


def _chunk(text, **kw):
    base = dict(doc_id="d", origin="mslearn", platform="d365fo", module="finance",
                title="T", source_ref="https://learn/x", ord=0)
    base.update(kw)
    return Chunk(text=text, **base)


def test_add_get_stats_roundtrip(tmp_path):
    with DocIndex(tmp_path / "docs.db") as di:
        n = di.add_chunks([
            _chunk("settlement matches invoices and payments", ord=0),
            _chunk("bank reconciliation statement", origin="internal", source_ref="C:/s.docx", ord=1),
        ])
        assert n == 2
        stats = di.stats()
        assert stats["chunks"] == 2
        assert stats["by_origin"] == {"mslearn": 1, "internal": 1}
        assert stats["has_vectors"] is False
        first = di.get(1)
        assert first["text"].startswith("T") and first["source_ref"] == "https://learn/x"
        assert di.get(999) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'd365fo_agent.doc_store'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/d365fo_agent/doc_store.py
"""Persistent SQLite + FTS5 index over D365 functional documentation chunks.

Separate from the AOT symbol index (``index_store.D365Index``): docs are PROSE, with citations
and (later) embeddings — a different shape from AOT symbol rows. Keeping them apart preserves the
clean symbol index and respects the project's prose-vs-symbol boundary. Standard library only.

The ``chunk_vectors`` table is created but unused in Phase 1 — the Phase 2 semantic layer fills
it, so no migration is needed later.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable

from d365fo_agent.doc_ingest import Chunk

SCHEMA_VERSION = 1


class DocIndex:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def __enter__(self) -> "DocIndex":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def _ensure_schema(self) -> None:
        c = self.conn
        c.execute(
            """CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                doc_id TEXT NOT NULL,
                origin TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'd365fo',
                module TEXT,
                title TEXT,
                source_ref TEXT,
                ord INTEGER DEFAULT 0,
                text TEXT NOT NULL
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_origin ON chunks(origin)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_module ON chunks(module)")
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS chunk_vectors (
                chunk_id INTEGER, model TEXT, dim INTEGER, vector BLOB
            )"""
        )
        c.execute("CREATE TABLE IF NOT EXISTS doc_meta (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT OR IGNORE INTO doc_meta(key, value) VALUES ('schema_version', ?)",
                  (str(SCHEMA_VERSION),))
        self.conn.commit()

    def add_chunks(self, chunks: Iterable[Chunk]) -> int:
        n = 0
        for ch in chunks:
            cur = self.conn.execute(
                "INSERT INTO chunks(doc_id, origin, platform, module, title, source_ref, ord, text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ch.doc_id, ch.origin, ch.platform, ch.module, ch.title, ch.source_ref, ch.ord, ch.text),
            )
            self.conn.execute("INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)",
                              (cur.lastrowid, ch.text))
            n += 1
        self.conn.commit()
        return n

    def get(self, chunk_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        return dict(row) if row else None

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        by_origin = {r[0]: r[1] for r in
                     self.conn.execute("SELECT origin, COUNT(*) FROM chunks GROUP BY origin")}
        has_vectors = self.conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] > 0
        return {"chunks": total, "by_origin": by_origin, "has_vectors": has_vectors}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_store.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/d365fo_agent/doc_store.py tests/test_doc_store.py
git commit -m "feat: DocIndex store (SQLite FTS5) with vector table prepared"
```

---

## Task 4: `DocIndex.search` — FTS5 BM25 + filters (`doc_store.py`)

**Files:**
- Modify: `src/d365fo_agent/doc_store.py`
- Test: `tests/test_doc_store.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_doc_store.py`)

```python
def test_search_ranks_and_filters(tmp_path):
    with DocIndex(tmp_path / "docs.db") as di:
        di.add_chunks([
            _chunk("settlement matches vendor invoices with payments", module="ap", ord=0),
            _chunk("general ledger journal posting", module="gl", ord=1),
            _chunk("ax 2012 settlement overlayering", platform="ax2012", module="ap", ord=2),
        ])
        hits = di.search("settlement payments")
        assert hits, "expected a hit for settlement"
        assert hits[0]["id"] == 1
        assert "source_ref" in hits[0] and "snippet" in hits[0]

        only_gl = di.search("posting", module="gl")
        assert all(h["module"] == "gl" for h in only_gl)

        d365_only = di.search("settlement", platform="d365fo")
        assert all(h["platform"] in ("d365fo", "both") for h in d365_only)


def test_search_empty_query_returns_empty(tmp_path):
    with DocIndex(tmp_path / "docs.db") as di:
        di.add_chunks([_chunk("anything")])
        assert di.search("   ") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_store.py -q`
Expected: FAIL — `AttributeError: 'DocIndex' object has no attribute 'search'`.

- [ ] **Step 3: Write minimal implementation** (append the method to the `DocIndex` class in `src/d365fo_agent/doc_store.py`)

```python
    def search(self, query: str, *, platform: str | None = None, module: str | None = None,
               origin: str | None = None, limit: int = 10) -> list[dict]:
        """FTS5 BM25 search over chunk text, newest filters applied. Each hit carries its
        source citation and a snippet. Empty/punctuation-only queries return []."""
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1]
        if not terms:
            return []
        match = " ".join(f'"{t}"' for t in terms)
        where = ["chunks_fts MATCH ?"]
        params: list[object] = [match]
        if platform:
            where.append("(c.platform = ? OR c.platform = 'both')")
            params.append(platform)
        if module:
            where.append("c.module = ?")
            params.append(module)
        if origin:
            where.append("c.origin = ?")
            params.append(origin)
        params.append(int(limit))
        sql = (
            "SELECT c.id, c.doc_id, c.origin, c.platform, c.module, c.title, c.source_ref, c.ord, "
            "snippet(chunks_fts, 0, '[', ']', ' … ', 16) AS snippet, bm25(chunks_fts) AS rank "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            f"WHERE {' AND '.join(where)} ORDER BY rank LIMIT ?"
        )
        return [dict(row) for row in self.conn.execute(sql, params)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_store.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/d365fo_agent/doc_store.py tests/test_doc_store.py
git commit -m "feat: DocIndex.search — FTS5 BM25 with platform/module/origin filters"
```

---

## Task 5: `build-doc-index` CLI command (`cli.py`)

**Files:**
- Modify: `src/d365fo_agent/cli.py` (dispatch block after the `build-ax-index` block, ~line 219; subparser in `_build_parser`, after `build_ax`, ~line 551)
- Test: `tests/test_doc_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_cli.py
import json
import zipfile
from pathlib import Path

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_cli.py -q`
Expected: FAIL — `SystemExit: 2` / "invalid choice: 'build-doc-index'".

- [ ] **Step 3a: Add the dispatch block** in `src/d365fo_agent/cli.py`, immediately AFTER the `build-ax-index` block (which ends with `return 0` at line ~219) and BEFORE the `extract-aot-relations` block:

```python
    if args.command == "build-doc-index":
        from d365fo_agent.doc_ingest import ingest_internal_dir, ingest_mslearn_dir
        from d365fo_agent.doc_store import DocIndex

        if not args.internal and not args.mslearn:
            parser.error("build-doc-index needs --internal (.docx folder) and/or --mslearn (markdown clone).")
        db_path = Path(args.db)
        if args.rebuild and db_path.exists():
            db_path.unlink()
        with DocIndex(db_path) as di:
            added = 0
            if args.mslearn:
                added += di.add_chunks(
                    ingest_mslearn_dir(Path(args.mslearn), base_url=args.mslearn_base_url, platform=args.platform)
                )
            if args.internal:
                added += di.add_chunks(ingest_internal_dir(Path(args.internal), platform=args.platform))
            _dump_json({"db": str(db_path).replace("\\", "/"), "chunks_added": added, **di.stats()})
        return 0
```

- [ ] **Step 3b: Add the subparser** in `_build_parser`, immediately AFTER the `build_ax` block (ends ~line 550) and before `extract_aot`:

```python
    build_doc = subparsers.add_parser(
        "build-doc-index",
        help="Build the documentation index (FTS5) from MS Learn markdown and/or internal .docx.",
    )
    build_doc.add_argument("--db", required=True, help="Output docs SQLite DB, e.g. .omx/index/docs.db")
    build_doc.add_argument("--mslearn", help="Local clone dir of MS Learn D365 F&O markdown.")
    build_doc.add_argument("--mslearn-base-url", help="Base URL for citations, e.g. https://learn.microsoft.com/en-us/dynamics365/finance")
    build_doc.add_argument("--internal", help="Folder of internal .docx specs (recursive).")
    build_doc.add_argument("--platform", default="d365fo", help="Platform tag for ingested docs: d365fo | ax2012 | both.")
    build_doc.add_argument("--rebuild", action="store_true", help="Delete and rebuild the DB from scratch.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_cli.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/d365fo_agent/cli.py tests/test_doc_cli.py
git commit -m "feat: build-doc-index CLI command"
```

---

## Task 6: MCP tools `search_docs` / `get_docs` / `docs_stats` + server wiring (`mcp_server.py`)

**Files:**
- Modify: `src/d365fo_agent/mcp_server.py` (`__init__` ~line 67; new helper after `_ax_index_if_ready` ~line 117; tools at the end of `_register_tools`, after `find_relations` ~line 751; `build_server_from_config` ~line 892; `main` argparse ~line 963)
- Modify: `src/d365fo_agent/cli.py` (`serve-mcp` dispatch ~line 241 and subparser ~line 579)
- Test: `tests/test_doc_mcp_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_mcp_tools.py
import json

from d365fo_agent.doc_ingest import Chunk
from d365fo_agent.doc_store import DocIndex
from d365fo_agent.mcp_server import build_server_from_config


def _server_with_docs(tmp_path):
    db = tmp_path / "docs.db"
    with DocIndex(db) as di:
        di.add_chunks([
            Chunk("d", "mslearn", "d365fo", "ap", "Settlement",
                  "https://learn/x/settlement", 0,
                  "Settlement\nSettlement matches vendor invoices with payments."),
        ])
    return build_server_from_config(db_path=tmp_path / "none.db", doc_db_path=db)


def _call(server, name, args):
    res = server._call_tool({"name": name, "arguments": args})
    assert res["isError"] is False
    return json.loads(res["content"][0]["text"])


def test_search_docs_returns_cited_hits(tmp_path):
    server = _server_with_docs(tmp_path)
    out = _call(server, "search_docs", {"query": "settlement payments"})
    assert out["found"] is True
    assert out["results"][0]["source_ref"] == "https://learn/x/settlement"


def test_get_docs_and_stats(tmp_path):
    server = _server_with_docs(tmp_path)
    chunk = _call(server, "get_docs", {"chunk_id": 1})
    assert chunk["title"] == "Settlement"
    stats = _call(server, "docs_stats", {})
    assert stats["chunks"] == 1


def test_doc_tools_degrade_without_index(tmp_path):
    server = build_server_from_config(db_path=tmp_path / "none.db")  # no doc_db_path
    out = _call(server, "search_docs", {"query": "anything"})
    assert out["found"] is False
    assert "build-doc-index" in out["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_mcp_tools.py -q`
Expected: FAIL — `TypeError: build_server_from_config() got an unexpected keyword argument 'doc_db_path'`.

- [ ] **Step 3a: Thread `doc_db_path` through `D365MCPServer.__init__`.** Add a parameter (after `ax_db_path` at line ~66) and store it + init the cache. In the signature add `doc_db_path: Path | None = None,`. In the body, after `self.ax_db_path = ax_db_path` (line ~69) add:

```python
        self.doc_db_path = doc_db_path
        self._doc_index: Any = None
```

- [ ] **Step 3b: Add the lazy helper** immediately after `_ax_index_if_ready` (after line ~117):

```python
    def _doc_index_if_ready(self) -> Any:
        """The documentation index when configured and present, else None — so doc tools degrade
        gracefully (like get_sql_model) instead of raising when no docs.db is wired."""
        if not self.doc_db_path or not Path(self.doc_db_path).exists():
            return None
        if self._doc_index is None:
            from d365fo_agent.doc_store import DocIndex

            self._doc_index = DocIndex(self.doc_db_path)
        return self._doc_index
```

- [ ] **Step 3c: Register the three tools** at the END of `_register_tools`, immediately after the `find_relations` handler (after line ~751, still inside the method, same indentation as the other `@tool` blocks):

```python
        _NO_DOCS = ("No documentation index configured. Build one with 'd365fo-agent build-doc-index' "
                    "and start the server with --doc-db / D365FO_DOC_DB.")

        @tool(
            "search_docs",
            "Search the INGESTED D365 functional documentation (MS Learn + internal specs) for "
            "prose that grounds a FUNCTIONAL question — e.g. 'how does vendor invoice matching work'. "
            "Use this to ground functional behaviour BEFORE writing it from memory; every hit carries "
            "its source citation (source_ref). Complements the AOT/symbol tools (which ground "
            "technical facts). Returns ranked chunks with a snippet, not full pages.",
            {"type": "object", "properties": {
                "query": STR, "platform": STR, "module": STR, "origin": STR, "limit": INT,
            }, "required": ["query"]},
        )
        def search_docs(args: dict[str, Any]) -> dict[str, Any]:
            di = self._doc_index_if_ready()
            if di is None:
                return {"found": False, "error": _NO_DOCS}
            return {"found": True, "results": di.search(
                args["query"], platform=args.get("platform"), module=args.get("module"),
                origin=args.get("origin"), limit=int(args.get("limit", 10)))}

        @tool(
            "get_docs",
            "Return one full documentation chunk by its id (from search_docs results), with its "
            "title, source citation and full text. Use to read the passage you intend to cite.",
            {"type": "object", "properties": {"chunk_id": INT}, "required": ["chunk_id"]},
        )
        def get_docs(args: dict[str, Any]) -> dict[str, Any]:
            di = self._doc_index_if_ready()
            if di is None:
                return {"found": False, "error": _NO_DOCS}
            chunk = di.get(int(args["chunk_id"]))
            return chunk if chunk else {"found": False, "error": f"No documentation chunk {args['chunk_id']}."}

        @tool(
            "docs_stats",
            "Report documentation-index coverage: chunk counts by origin (mslearn/internal) and "
            "whether semantic vectors are present. Use to see what functional docs are grounded.",
            {"type": "object", "properties": {}},
        )
        def docs_stats(args: dict[str, Any]) -> dict[str, Any]:
            di = self._doc_index_if_ready()
            if di is None:
                return {"found": False, "error": _NO_DOCS}
            return di.stats()
```

- [ ] **Step 3d: Accept + forward `doc_db_path` in `build_server_from_config`.** Add `doc_db_path: str | Path | None = None,` to the signature (after `ax_db_path`, line ~903). Before the `return D365MCPServer(...)` (line ~934), add resolution that defaults to a `docs.db` sibling of the knowledge DB:

```python
    doc_db = Path(doc_db_path).resolve() if doc_db_path else None
    if doc_db is None:
        sibling = db_path.parent / "docs.db"
        doc_db = sibling if sibling.exists() else None
```

Then add `doc_db_path=doc_db,` to the `D365MCPServer(...)` call's keyword arguments.

- [ ] **Step 3e: Add the `--doc-db` server arg in `mcp_server.main`.** After the `--ax-db` argument (line ~963) add:

```python
    parser.add_argument(
        "--doc-db", default=os.environ.get("D365FO_DOC_DB"),
        help="Documentation index (from build-doc-index) — enables search_docs/get_docs/docs_stats.",
    )
```

And add `doc_db_path=args.doc_db,` to the `build_server_from_config(...)` call (the one at line ~985).

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONPATH='src'; pytest tests/test_doc_mcp_tools.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/d365fo_agent/mcp_server.py tests/test_doc_mcp_tools.py
git commit -m "feat: search_docs/get_docs/docs_stats MCP tools with graceful degradation"
```

---

## Task 7: Wire `--doc-db` into the `serve-mcp` CLI + full suite + docs

**Files:**
- Modify: `src/d365fo_agent/cli.py` (`serve-mcp` dispatch ~line 241; subparser ~line 579)
- Modify: `README.md` (doc-grounding section) and `docs/mcp-server.md` (new tools + `--doc-db`)

- [ ] **Step 1: Add `--doc-db` to the `serve-mcp` subparser** in `_build_parser`, after `serve_mcp.add_argument("--methodology")` (line ~579):

```python
    serve_mcp.add_argument("--doc-db", help="Documentation index (from build-doc-index) — enables search_docs/get_docs.")
```

- [ ] **Step 2: Forward it in the `serve-mcp` dispatch** — add `doc_db_path=args.doc_db,` to the `build_server_from_config(...)` call inside the `if args.command == "serve-mcp":` block (line ~241).

- [ ] **Step 3: Run the FULL suite to confirm no regressions**

Run: `$env:PYTHONPATH='src'; pytest -q`
Expected: PASS — the prior ~194 tests plus the new doc tests, 0 failures. Also run `ruff check src/d365fo_agent/doc_ingest.py src/d365fo_agent/doc_store.py` and fix any lint.

- [ ] **Step 4: Document the feature** — add a short "Functional documentation grounding" section to `README.md` and `docs/mcp-server.md`:
  - build: `d365fo-agent build-doc-index --db .omx/index/docs.db --mslearn <clone> --mslearn-base-url https://learn.microsoft.com/en-us/dynamics365/finance --internal <docx-folder> --rebuild`
  - serve: add `--doc-db .omx/index/docs.db` to the `serve-mcp` invocation (or set `D365FO_DOC_DB`).
  - tools: `search_docs`, `get_docs`, `docs_stats` (note FTS5-only in Phase 1; semantic is a later optional extra).
  - note: MS Learn text is indexed locally from the public MicrosoftDocs clone; nothing is redistributed.

- [ ] **Step 5: Commit**

```bash
git add src/d365fo_agent/cli.py README.md docs/mcp-server.md
git commit -m "feat: wire --doc-db into serve-mcp; document doc-grounding"
```

---

## Self-Review (run after writing — checklist, not a subagent)

**1. Spec coverage** (against the design doc §4):
- `doc_ingest.py` (.docx stdlib extraction + markdown + chunking) → Tasks 1–2. ✓
- `doc_store.py` (`DocIndex` FTS5, vectors-prepared) → Tasks 3–4. ✓
- `search_docs`/`get_docs`/`docs_stats` MCP tools, graceful degradation → Task 6. ✓
- `build-doc-index` CLI → Task 5; `--doc-db` serve wiring → Tasks 6–7. ✓
- Citation on every hit (`source_ref`) → Tasks 4, 6 tests assert it. ✓
- Licensing (local text, no redistribution) → Task 7 docs note + design §2. ✓
- **Deferred (own next plan):** `embed.py`, `[semantic]` extra, `fetch-doc-vectors`, prebuilt vector asset — explicitly out of scope above. Schema readiness (`chunk_vectors`) is built in Task 3. ✓

**2. Placeholder scan:** every code/test step contains complete, runnable content. No TBD/TODO. ✓

**3. Type consistency:** `Chunk` fields (`doc_id, origin, platform, module, title, source_ref, ord, text`) are identical across `doc_ingest.py`, `doc_store.add_chunks`, and the tests. `DocIndex` methods (`add_chunks`, `search`, `get`, `stats`) and `_doc_index_if_ready()` match between definition and call sites. `search` returns dicts with `id`/`source_ref`/`snippet` — asserted consistently. ✓
