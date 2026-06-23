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
            # ch.text is already the canonical "title line + body" (see doc_ingest.chunk_paragraphs);
            # persist it verbatim. Re-prepending the title would duplicate it.
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

    def search(self, query: str, *, platform: str | None = None, module: str | None = None,
               origin: str | None = None, limit: int = 10) -> list[dict]:
        """FTS5 BM25 search over chunk text, with optional filters. Each hit carries its source
        citation and a snippet. Empty/punctuation-only queries return []."""
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

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        by_origin = {r[0]: r[1] for r in
                     self.conn.execute("SELECT origin, COUNT(*) FROM chunks GROUP BY origin")}
        has_vectors = self.conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] > 0
        return {"chunks": total, "by_origin": by_origin, "has_vectors": has_vectors}
