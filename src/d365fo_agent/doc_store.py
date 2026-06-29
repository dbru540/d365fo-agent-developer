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
          1. Run FTS5 with OR-recall (ANY term matches) for up to ``semantic_candidates``
             candidates — casts a wide net so natural-language queries are not gated by
             AND-of-all-terms. Pure FTS5 (``semantic=False``) keeps AND; single-term identical.
          2. Embed the query with ``"query: "`` prefix.
          3. Vector-recall (numpy, ``[semantic]`` extra): add the ``semantic_candidates`` chunks
             whose stored vectors are closest to the query — keyword-independent, so a French
             query reaches English passages via the multilingual model. Union with step 1.
          4. Rerank the merged candidates by cosine similarity (descending).
          5. Return the top ``limit`` hits.

        Chunks that lack a vector for ``model_name`` in ``chunk_vectors`` are excluded
        from the reranked results (they were never embedded for that model).

        Empty/punctuation-only queries return [].
        Terms shorter than 2 characters are dropped (FTS5 noise-word filter).
        """
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1]
        if not terms:
            return []

        # Hybrid retrieval (semantic=True + an embedder + vectors present for this model)
        # casts a WIDE net with OR-recall, then reranks by cosine for precision. Pure FTS5
        # keeps AND-of-all-terms for keyword precision. (Single-term queries: AND == OR.)
        hybrid = bool(
            semantic
            and embedder is not None
            and self.conn.execute(
                "SELECT 1 FROM chunk_vectors WHERE model = ? LIMIT 1", (model_name,)
            ).fetchone()
        )
        match_expr = (" OR " if hybrid else " ").join(f'"{t}"' for t in terms)
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

        candidate_limit = semantic_candidates if hybrid else limit
        params.append(int(candidate_limit))

        sql = (
            "SELECT c.id, c.doc_id, c.origin, c.platform, c.module, c.title, c.source_ref, c.ord, "
            "snippet(chunks_fts, 0, '[', ']', ' … ', 16) AS snippet, bm25(chunks_fts) AS rank "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            f"WHERE {' AND '.join(where)} ORDER BY rank LIMIT ?"
        )
        candidates = [dict(row) for row in self.conn.execute(sql, params)]

        # --- Hybrid: embed query, add vector-recall candidates, then cosine-rerank ----------
        if not hybrid:
            return candidates[:limit]

        # Embed the query (FakeEmbedder yields a list; real fastembed yields a float32 array —
        # both iterable — convert to plain floats either way).
        try:
            q_floats = [float(x) for x in list(embedder.embed([f"query: {query}"]))[0]]
        except Exception:
            return candidates[:limit]
        if not any(q_floats):
            return candidates[:limit]

        # Vector-recall: brute-force cosine over ALL stored vectors (NOT keyword-gated), so
        # cross-lingual / paraphrased queries surface relevant chunks the FTS net misses — e.g. a
        # French query matching English passages via the multilingual model. Union the recalled
        # rows with the FTS-OR candidates; the cosine rerank below orders the merged set. Requires
        # numpy (ships with the [semantic] extra); silently no-ops to FTS-only recall without it.
        seen = {row["id"] for row in candidates}
        for row in self._vector_recall_rows(
            q_floats, model_name, semantic_candidates,
            platform=platform, module=module, origin=origin,
        ):
            if row["id"] not in seen:
                candidates.append(row)
                seen.add(row["id"])

        if not candidates:
            return []

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

    def _vector_recall_rows(
        self,
        q_floats: list[float],
        model_name: str,
        top_n: int,
        *,
        platform: str | None = None,
        module: str | None = None,
        origin: str | None = None,
    ) -> list[dict]:
        """Up to ``top_n`` chunk rows whose stored vectors are closest (cosine) to ``q_floats`` —
        a keyword-independent recall step that enables cross-lingual / paraphrase matching.

        Uses numpy (present with the ``[semantic]`` extra) to brute-force the cosine over every
        stored vector for ``model_name``; returns [] when numpy is absent, no vectors exist, or
        the query dimensionality differs from the stored vectors. The normalized matrix is cached
        per model on the instance (~ vectors × dim × 4 bytes) and reused across queries.
        """
        try:
            import numpy as np
        except Exception:
            return []

        cache = getattr(self, "_vec_cache", None)
        if cache is None:
            cache = self._vec_cache = {}
        if model_name not in cache:
            rows = self.conn.execute(
                "SELECT chunk_id, vector FROM chunk_vectors WHERE model = ? ORDER BY chunk_id",
                (model_name,),
            ).fetchall()
            if rows:
                ids = [int(r[0]) for r in rows]
                mat = np.frombuffer(
                    b"".join(r[1] for r in rows), dtype=np.float32
                ).reshape(len(ids), -1)
                norms = np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-8, None)
                cache[model_name] = (ids, mat / norms)
            else:
                cache[model_name] = ([], None)
        ids, matn = cache[model_name]
        if matn is None or not ids:
            return []

        qv = np.asarray(q_floats, dtype=np.float32)
        if qv.shape[0] != matn.shape[1]:
            return []  # dimension mismatch (different model) — skip vector recall
        nq = float(np.linalg.norm(qv))
        if nq == 0.0:
            return []
        sims = matn @ (qv / nq)
        k = min(int(top_n), int(sims.shape[0]))
        if k <= 0:
            return []
        top = np.argpartition(-sims, k - 1)[:k]
        top_ids = [int(ids[i]) for i in top]

        where = ["id IN (%s)" % ",".join("?" * len(top_ids))]
        params: list[object] = list(top_ids)
        if platform:
            where.append("(platform = ? OR platform = 'both')")
            params.append(platform)
        if module:
            where.append("module = ?")
            params.append(module)
        if origin:
            where.append("origin = ?")
            params.append(origin)
        sql = (
            "SELECT id, doc_id, origin, platform, module, title, source_ref, ord, text "
            f"FROM chunks WHERE {' AND '.join(where)}"
        )
        out: list[dict] = []
        for r in self.conn.execute(sql, params):
            d = dict(r)
            text = d.pop("text", "") or ""
            d["snippet"] = text[:200]
            d["rank"] = None
            out.append(d)
        return out

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
