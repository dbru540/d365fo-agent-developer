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
import struct
from pathlib import Path
from typing import Iterable

from d365fo_agent.doc_ingest import Chunk


def _floats_to_blob(vec) -> bytes:
    """Encode an iterable of floats as little-endian float32 bytes (numpy-tobytes compatible)."""
    floats = [float(x) for x in vec]
    return struct.pack(f"<{len(floats)}f", *floats)


def _blob_to_floats(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob)) if n else []


def _cosine_floats(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


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

    def search(
        self,
        query: str,
        *,
        platform: str | None = None,
        module: str | None = None,
        origin: str | None = None,
        limit: int = 10,
        semantic: bool = False,
        embedder: object | None = None,
        model_name: str = "intfloat/multilingual-e5-small",
        semantic_candidates: int = 40,
    ) -> list[dict]:
        """Search chunks by BM25 (default) or hybrid BM25→cosine-rerank (``semantic=True``).

        FTS5-only path:
          ``semantic=False`` (default), or ``semantic=True`` but no vectors are present, or
          no ``embedder`` is supplied → identical to the Phase 1 behaviour.

        Hybrid path (``semantic=True`` + vectors present + embedder supplied):
          1. Run FTS5 to get up to ``semantic_candidates`` candidates.
          2. Embed the query with ``"query: "`` prefix.
          3. Load the stored vector for each candidate from ``chunk_vectors``.
          4. Rerank by cosine similarity (descending).
          5. Return the top ``limit`` hits.

        Chunks that lack a vector for ``model_name`` in ``chunk_vectors`` are excluded
        from the reranked results (they were never embedded for that model).

        Empty/punctuation-only queries return [].
        Terms shorter than 2 characters are dropped (FTS5 noise-word filter).
        """
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1]
        if not terms:
            return []

        match_expr = " ".join(f'"{t}"' for t in terms)
        where = ["chunks_fts MATCH ?"]
        params: list[object] = [match_expr]
        if platform:
            where.append("(c.platform = ? OR c.platform = 'both')")
            params.append(platform)
        if module:
            where.append("c.module = ?")
            params.append(module)
        if origin:
            where.append("c.origin = ?")
            params.append(origin)

        candidate_limit = semantic_candidates if semantic else limit
        params.append(int(candidate_limit))

        sql = (
            "SELECT c.id, c.doc_id, c.origin, c.platform, c.module, c.title, c.source_ref, c.ord, "
            "snippet(chunks_fts, 0, '[', ']', ' … ', 16) AS snippet, bm25(chunks_fts) AS rank "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            f"WHERE {' AND '.join(where)} ORDER BY rank LIMIT ?"
        )
        candidates = [dict(row) for row in self.conn.execute(sql, params)]

        # --- Hybrid rerank (optional) --------------------------------------------
        if not (semantic and embedder and candidates):
            return candidates[:limit]

        # Check whether chunk_vectors has rows for this model.
        has_vectors = (
            self.conn.execute(
                "SELECT COUNT(*) FROM chunk_vectors WHERE model = ?", (model_name,)
            ).fetchone()[0]
            > 0
        )
        if not has_vectors:
            return candidates[:limit]  # degrade gracefully

        # Embed the query (FakeEmbedder yields a list; real fastembed yields a float32 array —
        # both iterable — convert to plain floats either way).
        try:
            q_floats = [float(x) for x in list(embedder.embed([f"query: {query}"]))[0]]
        except Exception:
            return candidates[:limit]
        if not any(q_floats):
            return candidates[:limit]

        scored: list[tuple[float, dict]] = []
        for row in candidates:
            vec_row = self.conn.execute(
                "SELECT vector FROM chunk_vectors WHERE chunk_id = ? AND model = ?",
                (row["id"], model_name),
            ).fetchone()
            if vec_row is None:
                continue
            sim = _cosine_floats(q_floats, _blob_to_floats(vec_row[0]))
            scored.append((sim, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [row for _, row in scored[:limit]]

    def add_vectors(
        self,
        embedder: object,
        *,
        model_name: str = "intfloat/multilingual-e5-small",
        dim: int = 384,
        batch_size: int = 64,
    ) -> int:
        """Populate ``chunk_vectors`` for any chunk that does not yet have a vector for
        ``model_name``.  ``embedder`` must implement ``embed(list[str]) -> Iterable``
        (the fastembed TextEmbedding interface — or any compatible fake/stub).

        Returns the number of new vectors stored.  Idempotent: already-vectorised chunks
        are skipped (checked by ``chunk_id`` + ``model``).
        """
        existing = {
            row[0]
            for row in self.conn.execute(
                "SELECT chunk_id FROM chunk_vectors WHERE model = ?", (model_name,)
            )
        }
        rows = self.conn.execute(
            "SELECT id, text FROM chunks ORDER BY id"
        ).fetchall()
        pending = [(row["id"], row["text"]) for row in rows if row["id"] not in existing]
        if not pending:
            return 0

        n = 0
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            ids = [item[0] for item in batch]
            texts = [f"passage: {item[1]}" for item in batch]
            vectors = list(embedder.embed(texts))
            for chunk_id, vec in zip(ids, vectors):
                blob = _floats_to_blob(vec)
                self.conn.execute(
                    "INSERT INTO chunk_vectors(chunk_id, model, dim, vector) VALUES (?, ?, ?, ?)",
                    (chunk_id, model_name, dim, blob),
                )
                n += 1
        self.conn.commit()
        return n

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        by_origin = {r[0]: r[1] for r in
                     self.conn.execute("SELECT origin, COUNT(*) FROM chunks GROUP BY origin")}
        has_vectors = self.conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0] > 0
        return {"chunks": total, "by_origin": by_origin, "has_vectors": has_vectors}
