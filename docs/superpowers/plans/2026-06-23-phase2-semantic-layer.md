# Phase 2 — Semantic Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional semantic (vector) layer on top of the existing FTS5 doc index. When the `[semantic]` extra is installed, `search_docs` uses a hybrid FTS5 → cosine-rerank path; when it is absent the system stays pure FTS5 with zero behaviour change. Deliver code + tests on fakes/fixtures — the real model download and corpus embedding are deferred (the user provides data later).

**Architecture:** Mirror the Phase 1 degradation pattern (xppc/index absent → graceful degrade). `embed.py` is the new module; it lazy-imports `fastembed` and exposes `EMBED_AVAILABLE`. `doc_store.DocIndex` gains `add_vectors(embedder)` and a hybrid `search(..., semantic=True)` path. The CLI gains `--embed` on `build-doc-index` and a new `fetch-doc-vectors` command (mirroring `knowledge_fetch.fetch_knowledge`). The MCP `search_docs` tool gains an optional `semantic` boolean arg.

**Tech Stack:** Python 3.11+, standard library only in the base package. The `[semantic]` extra adds `fastembed` (which ships numpy). No torch. Tests: `pytest`, `ruff`.

**Model:** `intfloat/multilingual-e5-small`, dim 384, MEAN pooling, normalization=True, registered via `fastembed.TextEmbedding.add_custom_model`. Prefixes: documents → `"passage: "`, queries → `"query: "`.

**Out of scope (deferred):** the real model download from HuggingFace, embedding the live MS Learn corpus, and the prebuilt vector asset release. This plan ships code + unit tests only; those tests that need real fastembed are skip-guarded with `pytest.mark.skipif`.

---

## File Structure

- **Create** `src/d365fo_agent/embed.py` — `EMBED_AVAILABLE`, `get_embedder`, `embed_passages`, `embed_query`, `vector_to_blob`, `blob_to_vector`, `cosine`.
- **Modify** `pyproject.toml` — add `semantic = ["fastembed"]` under `[project.optional-dependencies]`.
- **Modify** `src/d365fo_agent/doc_store.py` — add `add_vectors(embedder)`, extend `search` with `semantic` kwarg and hybrid rerank.
- **Modify** `src/d365fo_agent/cli.py` — add `--embed` to `build-doc-index`; add `fetch-doc-vectors` command + subparser.
- **Modify** `src/d365fo_agent/mcp_server.py` — add optional `semantic` boolean arg to `search_docs` tool.
- **Modify** `README.md` + `docs/mcp-server.md` — note `[semantic]` extra, e5 model, `--embed`, `fetch-doc-vectors`, FTS5 degradation.
- **Create** `tests/test_embed.py`, **Modify** `tests/test_doc_store.py`, `tests/test_doc_cli.py`, `tests/test_doc_mcp_tools.py`.

Run all tests with: `$env:PYTHONPATH='src'; pytest -q` (PowerShell) — POSIX: `PYTHONPATH=src pytest -q`.

---

## Task 1: `pyproject.toml` — add `[semantic]` optional extra

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing test**

There is no pytest test for `pyproject.toml` content; the "test" here is a manual verification command that must fail first. Run:

```powershell
# PowerShell — confirm the extra does NOT exist yet (before the edit)
Select-String -Path pyproject.toml -Pattern '"fastembed"'
# Expected: no output (zero matches)
```

- [ ] **Step 2: Confirm absence**

Run the command above. If output is empty, proceed. If `fastembed` already appears, something is wrong — stop and investigate.

- [ ] **Step 3: Write minimal implementation**

In `pyproject.toml`, locate the `[project.optional-dependencies]` section:

```toml
[project.optional-dependencies]
# The graph-building engine is the ONLY external dependency, and only the
# `run-graphify-staging` command needs it. Everything else (indexing, generation,
# MCP server, validation) is Python standard library only.
graph = ["graphify"]
dev = ["pytest", "ruff", "build"]
```

Add `semantic` immediately after `graph`:

```toml
[project.optional-dependencies]
# The graph-building engine is the ONLY external dependency, and only the
# `run-graphify-staging` command needs it. Everything else (indexing, generation,
# MCP server, validation) is Python standard library only.
graph = ["graphify"]
semantic = ["fastembed"]
dev = ["pytest", "ruff", "build"]
```

- [ ] **Step 4: Verify the extra is present**

```powershell
Select-String -Path pyproject.toml -Pattern '"fastembed"'
# Expected: one match on the semantic = ["fastembed"] line
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add optional [semantic] extra (fastembed) to pyproject"
```

---

## Task 2: `embed.py` — pure helpers, `EMBED_AVAILABLE`, `get_embedder`, `embed_passages`, `embed_query`

**Files:**
- Create: `src/d365fo_agent/embed.py`
- Create: `tests/test_embed.py`

### Why this split matters

The pure helpers (`vector_to_blob`, `blob_to_vector`, `cosine`, prefix application) do NOT need fastembed; they are testable without it. Only `get_embedder`, `embed_passages`, and `embed_query` call into fastembed — those tests are skip-guarded. This mirrors how the project tests `xppc` absence.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embed.py
"""Tests for embed.py — pure helpers run always; embedder tests are skip-guarded."""
import struct
import unittest

# ---------------------------------------------------------------------------
# Availability flag — checked at import time; usable as a skip guard anywhere.
# ---------------------------------------------------------------------------
try:
    from d365fo_agent.embed import EMBED_AVAILABLE
except ImportError:
    EMBED_AVAILABLE = False

# ---------------------------------------------------------------------------
# Conditional import — the module must be importable even without fastembed.
# ---------------------------------------------------------------------------
from d365fo_agent.embed import (  # noqa: E402  (after try/except above)
    blob_to_vector,
    cosine,
    embed_passages,
    embed_query,
    get_embedder,
    vector_to_blob,
)


class TestPureHelpers(unittest.TestCase):
    """These tests run in the base (no-extra) environment — no fastembed needed."""

    def test_vector_to_blob_round_trips(self):
        import struct
        vec = [1.0, 0.5, -0.25]
        blob = vector_to_blob(vec)
        assert isinstance(blob, bytes)
        assert len(blob) == 12  # 3 × 4 bytes
        back = blob_to_vector(blob)
        # numpy ndarray — compare element-wise
        for a, b in zip(vec, back.tolist()):
            assert abs(a - b) < 1e-6

    def test_blob_to_vector_returns_float32_ndarray(self):
        try:
            import numpy as np
            vec = [1.0, 2.0, 3.0]
            blob = vector_to_blob(vec)
            arr = blob_to_vector(blob)
            assert arr.dtype == np.float32
            assert arr.shape == (3,)
        except ImportError:
            self.skipTest("numpy not available (fastembed extra not installed)")

    def test_cosine_identical_vectors_is_one(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not available")
        vec = [1.0, 0.0, 0.0]
        blob = vector_to_blob(vec)
        score = cosine(blob, blob)
        assert abs(score - 1.0) < 1e-6

    def test_cosine_orthogonal_vectors_is_zero(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not available")
        a = vector_to_blob([1.0, 0.0, 0.0])
        b = vector_to_blob([0.0, 1.0, 0.0])
        score = cosine(a, b)
        assert abs(score) < 1e-6

    def test_cosine_opposite_vectors_is_minus_one(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not available")
        a = vector_to_blob([1.0, 0.0])
        b = vector_to_blob([-1.0, 0.0])
        score = cosine(a, b)
        assert abs(score - (-1.0)) < 1e-6


# ---------------------------------------------------------------------------
# Embedder tests — skip-guarded: only run when fastembed is installed.
# ---------------------------------------------------------------------------
@unittest.skipUnless(EMBED_AVAILABLE, "fastembed extra not installed — skipping embedder tests")
class TestEmbedder(unittest.TestCase):
    """Require real fastembed. Skipped in the base (stdlib-only) environment."""

    def test_get_embedder_returns_text_embedding_instance(self):
        from fastembed import TextEmbedding
        emb = get_embedder()
        assert isinstance(emb, TextEmbedding)

    def test_embed_passages_returns_list_of_bytes(self):
        texts = ["settlement matches vendor invoices", "bank reconciliation"]
        blobs = embed_passages(texts)
        assert isinstance(blobs, list)
        assert len(blobs) == 2
        for b in blobs:
            assert isinstance(b, bytes)
            assert len(b) == 384 * 4  # float32 × 384 dims

    def test_embed_query_returns_bytes(self):
        blob = embed_query("how does vendor invoice matching work?")
        assert isinstance(blob, bytes)
        assert len(blob) == 384 * 4

    def test_embed_passages_applies_passage_prefix(self):
        """Verify the prefix is applied: embed 'passage: X' directly vs embed_passages(['X'])
        should give the same vector (or very close — the wrapper must add the prefix)."""
        import numpy as np
        emb = get_embedder()
        raw = list(emb.embed(["passage: hello world"]))
        via_helper = blob_to_vector(embed_passages(["hello world"])[0])
        direct = raw[0]
        # cosine similarity should be ≥ 0.999
        sim = float(np.dot(direct, via_helper) / (np.linalg.norm(direct) * np.linalg.norm(via_helper)))
        assert sim >= 0.999

    def test_embed_query_applies_query_prefix(self):
        import numpy as np
        emb = get_embedder()
        raw = list(emb.embed(["query: hello world"]))
        via_helper = blob_to_vector(embed_query("hello world"))
        direct = raw[0]
        sim = float(np.dot(direct, via_helper) / (np.linalg.norm(direct) * np.linalg.norm(via_helper)))
        assert sim >= 0.999
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_embed.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'd365fo_agent.embed'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/d365fo_agent/embed.py
"""Optional semantic embedding layer for the D365 doc index.

The base package is standard-library-only. This module lazy-imports ``fastembed``
inside functions so the module is always importable — ``EMBED_AVAILABLE`` tells
callers whether the extra is actually installed.

Model: ``intfloat/multilingual-e5-small`` (dim 384, MEAN pooling, multilingual FR/EN).
Registered once via ``TextEmbedding.add_custom_model`` (guarded against double-registration).

e5 prefix convention (required by the model):
  documents → ``"passage: "``   (stored in chunk_vectors)
  queries   → ``"query: "``     (applied at search time, never stored)

Blob encoding: ``np.asarray(v, dtype="float32").tobytes()`` → 4 × dim bytes.
Reload:        ``np.frombuffer(blob, dtype="float32")`` → float32 ndarray.
numpy ships with fastembed; blob helpers guard their numpy import so that
``vector_to_blob`` / ``blob_to_vector`` / ``cosine`` are testable without fastembed
only when numpy is available (which it is when the extra is installed).
"""

from __future__ import annotations

_MODEL_NAME = "intfloat/multilingual-e5-small"
_DIM = 384

# ---------------------------------------------------------------------------
# Availability flag — set at import time; never raises.
# ---------------------------------------------------------------------------
try:
    import fastembed as _fastembed_probe  # noqa: F401

    EMBED_AVAILABLE: bool = True
except ImportError:
    EMBED_AVAILABLE = False


# ---------------------------------------------------------------------------
# Pure blob helpers — usable without fastembed IF numpy is available (it ships
# with fastembed, so numpy ↔ EMBED_AVAILABLE in practice).
# ---------------------------------------------------------------------------

def vector_to_blob(vector: list[float] | "np.ndarray") -> bytes:
    """Encode a float vector to a raw bytes blob (float32, little-endian)."""
    import numpy as np

    return np.asarray(vector, dtype="float32").tobytes()


def blob_to_vector(blob: bytes) -> "np.ndarray":
    """Decode a raw bytes blob back to a float32 numpy array."""
    import numpy as np

    return np.frombuffer(blob, dtype="float32")


def cosine(a_blob: bytes, b_blob: bytes) -> float:
    """Cosine similarity between two blobs. Returns float in [-1, 1]."""
    import numpy as np

    a = blob_to_vector(a_blob)
    b = blob_to_vector(b_blob)
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Embedder — lazy-imports fastembed; raises ImportError if extra is absent.
# ---------------------------------------------------------------------------

_embedder_cache: dict[str, object] = {}


def _register_model() -> None:
    """Register the multilingual-e5-small model with fastembed if not already known.

    fastembed raises ``ValueError`` when ``add_custom_model`` is called twice with
    the same model name (the model is already in the registry).  We suppress that
    specific error so repeated calls are idempotent.
    """
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    try:
        TextEmbedding.add_custom_model(
            model=_MODEL_NAME,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=_MODEL_NAME),
            dim=_DIM,
            model_file="onnx/model.onnx",
        )
    except Exception as exc:  # noqa: BLE001
        # The common case is "already registered" (idempotent re-call). Surface anything
        # unexpected to stderr instead of swallowing it silently — otherwise a wrong
        # fastembed import path would degrade to FTS5 with no diagnostic.
        import sys

        if "already" not in str(exc).lower() and "exist" not in str(exc).lower():
            print(f"[embed] add_custom_model({_MODEL_NAME!r}) failed: {exc}", file=sys.stderr)


def get_embedder(model_name: str = _MODEL_NAME) -> "fastembed.TextEmbedding":
    """Return a cached ``TextEmbedding`` instance for ``model_name``.

    Raises ``ImportError`` when the ``[semantic]`` extra is not installed — callers
    must check ``EMBED_AVAILABLE`` before calling this.
    """
    from fastembed import TextEmbedding

    if model_name not in _embedder_cache:
        _register_model()
        _embedder_cache[model_name] = TextEmbedding(model_name=model_name)
    return _embedder_cache[model_name]  # type: ignore[return-value]


def embed_passages(texts: list[str], model_name: str = _MODEL_NAME) -> list[bytes]:
    """Embed a list of document passages (adds ``"passage: "`` prefix, stores as blobs).

    Raises ``ImportError`` when the ``[semantic]`` extra is not installed.
    """
    emb = get_embedder(model_name)
    prefixed = [f"passage: {t}" for t in texts]
    return [vector_to_blob(v) for v in emb.embed(prefixed)]


def embed_query(text: str, model_name: str = _MODEL_NAME) -> bytes:
    """Embed a single query string (adds ``"query: "`` prefix, returns blob).

    Raises ``ImportError`` when the ``[semantic]`` extra is not installed.
    """
    emb = get_embedder(model_name)
    vectors = list(emb.embed([f"query: {text}"]))
    return vector_to_blob(vectors[0])
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_embed.py -q
```

Expected: Pure-helper tests pass (or are skipped where numpy is absent). Embedder tests are skipped with `"fastembed extra not installed"` unless the extra is installed. Overall result: PASS (no failures; some skips are fine).

- [ ] **Step 5: Run ruff**

```powershell
$env:PYTHONPATH='src'; ruff check src/d365fo_agent/embed.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/d365fo_agent/embed.py tests/test_embed.py
git commit -m "feat: embed.py — EMBED_AVAILABLE flag, Embedder wrapper, blob helpers, cosine"
```

---

## Task 3: `DocIndex.add_vectors` — populate `chunk_vectors` from an embedder

**Files:**
- Modify: `src/d365fo_agent/doc_store.py`
- Test: `tests/test_doc_store.py`

The `chunk_vectors` table (`chunk_id, model, dim, vector BLOB`) already exists (Phase 1, Task 3). This task fills it using a caller-supplied embedder — real or fake. The fake lets us test without fastembed.

- [ ] **Step 1: Write the failing test** (append to `tests/test_doc_store.py`)

```python
# ---------------------------------------------------------------------------
# Fake embedder — deterministic, no fastembed needed.
# Maps text fragments to fixed small float32 vectors (dim 3 for speed).
# ---------------------------------------------------------------------------
class FakeEmbedder:
    """Deterministic in-test embedder that maps known text substrings to fixed vectors.

    embed(texts) accepts a list of prefixed strings (e.g. "passage: settlement …") and
    returns a generator of float32 numpy arrays — the same interface as fastembed's
    TextEmbedding.embed().  Unknown texts get a zero vector.
    """
    _MAP = {
        "settlement": [1.0, 0.0, 0.0],
        "reconciliation": [0.0, 1.0, 0.0],
        "journal": [0.0, 0.0, 1.0],
    }
    _DIM = 3

    def embed(self, texts):
        import numpy as np
        for text in texts:
            t = text.lower()
            vec = None
            for key, v in self._MAP.items():
                if key in t:
                    vec = v
                    break
            yield np.asarray(vec if vec else [0.0] * self._DIM, dtype="float32")


def _make_index_with_chunks(tmp_path):
    """Helper: DocIndex with three chunks and no vectors yet."""
    from d365fo_agent.doc_store import DocIndex

    di = DocIndex(tmp_path / "docs.db")
    di.add_chunks([
        _chunk("settlement matches vendor invoices", ord=0, module="ap"),
        _chunk("bank reconciliation statement", ord=1, module="gl"),
        _chunk("general ledger journal posting", ord=2, module="gl"),
    ])
    return di


def test_add_vectors_populates_chunk_vectors(tmp_path):
    """add_vectors fills chunk_vectors for all chunks that lack a vector."""
    di = _make_index_with_chunks(tmp_path)
    embedder = FakeEmbedder()
    n = di.add_vectors(embedder, model_name="fake/dim3", dim=3)
    assert n == 3
    stats = di.stats()
    assert stats["has_vectors"] is True
    di.close()


def test_add_vectors_is_idempotent(tmp_path):
    """Calling add_vectors twice does not duplicate rows for already-vectorised chunks."""
    di = _make_index_with_chunks(tmp_path)
    embedder = FakeEmbedder()
    di.add_vectors(embedder, model_name="fake/dim3", dim=3)
    n2 = di.add_vectors(embedder, model_name="fake/dim3", dim=3)
    assert n2 == 0  # nothing new to embed
    count = di.conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
    assert count == 3  # still exactly 3, not 6
    di.close()
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_doc_store.py -q -k "add_vectors"
```

Expected: FAIL — `AttributeError: 'DocIndex' object has no attribute 'add_vectors'`.

- [ ] **Step 3: Write minimal implementation** (append method to `DocIndex` class in `src/d365fo_agent/doc_store.py`)

```python
    def add_vectors(
        self,
        embedder: object,
        *,
        model_name: str = "intfloat/multilingual-e5-small",
        dim: int = 384,
        batch_size: int = 64,
    ) -> int:
        """Populate ``chunk_vectors`` for any chunk that does not yet have a vector for
        ``model_name``.  ``embedder`` must implement ``embed(list[str]) -> Iterable[ndarray]``
        (the fastembed TextEmbedding interface — or any compatible fake/stub).

        Returns the number of new vectors stored.  Idempotent: already-vectorised chunks
        are skipped (checked by ``chunk_id`` + ``model``).
        """
        # Determine which chunk ids already have a vector for this model.
        existing = {
            row[0]
            for row in self.conn.execute(
                "SELECT chunk_id FROM chunk_vectors WHERE model = ?", (model_name,)
            )
        }
        # Fetch all chunks lacking a vector.
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
                import numpy as np

                blob = np.asarray(vec, dtype="float32").tobytes()
                self.conn.execute(
                    "INSERT INTO chunk_vectors(chunk_id, model, dim, vector) VALUES (?, ?, ?, ?)",
                    (chunk_id, model_name, dim, blob),
                )
                n += 1
        self.conn.commit()
        return n
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_doc_store.py -q -k "add_vectors"
```

Expected: PASS (2 passed).

- [ ] **Step 5: Run the full `test_doc_store.py` to confirm no regressions**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_doc_store.py -q
```

Expected: PASS (all prior tests + 2 new = 5 passed).

- [ ] **Step 6: Commit**

```bash
git add src/d365fo_agent/doc_store.py tests/test_doc_store.py
git commit -m "feat: DocIndex.add_vectors — populate chunk_vectors from embedder, idempotent"
```

---

## Task 4: `DocIndex.search` hybrid path — FTS5 top-N then cosine rerank

**Files:**
- Modify: `src/d365fo_agent/doc_store.py`
- Test: `tests/test_doc_store.py`

The existing `search(query, ...)` stays FTS5-only when `semantic=False` (default) or when vectors are absent. When `semantic=True` AND vectors exist AND an embedder is supplied, take the FTS5 top-N candidates (N = `semantic_candidates`, default 40) and rerank by cosine similarity to the query vector — return `limit` results.

The fake embedder maps text keywords to orthogonal axes, making rerank ORDER fully deterministic in tests.

- [ ] **Step 1: Write the failing test** (append to `tests/test_doc_store.py`)

```python
def test_search_semantic_reranks_candidates(tmp_path):
    """Hybrid search must reorder results by cosine similarity, not BM25.

    FakeEmbedder maps:
      "settlement" → [1, 0, 0]
      "reconciliation" → [0, 1, 0]
      "journal" → [0, 0, 1]
    The query "reconciliation" maps to [0, 1, 0].
    After FTS5 top-N we rerank by cosine: the reconciliation chunk must rank first,
    even if BM25 would rank it second.
    """
    from d365fo_agent.doc_store import DocIndex

    di = DocIndex(tmp_path / "docs.db")
    # Add chunks in an order where FTS5 might rank "settlement" higher on a multi-keyword query.
    di.add_chunks([
        _chunk("settlement reconciliation vendor payments", ord=0, module="ap"),   # id=1 — contains both
        _chunk("bank reconciliation statement monthly", ord=1, module="gl"),        # id=2 — pure reconciliation
        _chunk("general ledger journal posting entries", ord=2, module="gl"),       # id=3 — unrelated
    ])
    embedder = FakeEmbedder()
    di.add_vectors(embedder, model_name="fake/dim3", dim=3)

    # Semantic query for "reconciliation" → vector [0,1,0]
    results = di.search("reconciliation", semantic=True, embedder=embedder,
                        model_name="fake/dim3")
    assert results, "expected at least one result"
    # The pure reconciliation chunk (id=2) should rank above the mixed one (id=1).
    ids = [r["id"] for r in results]
    assert ids.index(2) < ids.index(1), (
        f"Expected id=2 before id=1 in semantic rerank; got order {ids}"
    )
    di.close()


def test_search_semantic_degrades_without_vectors(tmp_path):
    """When no vectors are present, semantic=True falls back to FTS5 silently."""
    from d365fo_agent.doc_store import DocIndex

    di = DocIndex(tmp_path / "docs.db")
    di.add_chunks([_chunk("settlement reconciliation", ord=0)])
    # No add_vectors call — has_vectors is False.
    results = di.search("settlement", semantic=True, embedder=FakeEmbedder(),
                        model_name="fake/dim3")
    assert results  # FTS5 fallback still returns results
    di.close()


def test_search_semantic_false_unchanged(tmp_path):
    """semantic=False (default) must produce the same results as before this task."""
    from d365fo_agent.doc_store import DocIndex

    di = DocIndex(tmp_path / "docs.db")
    di.add_chunks([_chunk("settlement matches vendor invoices", ord=0)])
    results = di.search("settlement")
    assert results[0]["id"] == 1
    di.close()
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_doc_store.py -q -k "semantic"
```

Expected: FAIL — `TypeError: search() got an unexpected keyword argument 'semantic'`.

- [ ] **Step 3: Write minimal implementation** — extend `search` in `src/d365fo_agent/doc_store.py`

Replace the existing `search` method signature and body with the extended version below. The FTS5 path is preserved exactly; the hybrid path is a post-filter.

```python
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

        # --- Determine effective candidate count ----------------------------------
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

        # Check whether chunk_vectors has rows for this model (fast count check).
        has_vectors = (
            self.conn.execute(
                "SELECT COUNT(*) FROM chunk_vectors WHERE model = ?", (model_name,)
            ).fetchone()[0]
            > 0
        )
        if not has_vectors:
            return candidates[:limit]  # degrade gracefully

        # Embed the query (lazy import of embed helpers — avoids hard dep at module level).
        try:
            import numpy as np

            q_vec_raw = list(embedder.embed([f"query: {query}"]))
            q_vec = np.asarray(q_vec_raw[0], dtype="float32")
            q_norm = float(np.linalg.norm(q_vec))
            if q_norm == 0.0:
                return candidates[:limit]
            q_unit = q_vec / q_norm
        except Exception:
            return candidates[:limit]  # any failure → FTS5 fallback

        # Load stored vectors for each candidate.
        scored: list[tuple[float, dict]] = []
        for row in candidates:
            vec_row = self.conn.execute(
                "SELECT vector FROM chunk_vectors WHERE chunk_id = ? AND model = ?",
                (row["id"], model_name),
            ).fetchone()
            if vec_row is None:
                continue  # no vector for this model — skip from semantic results
            try:
                d_vec = np.frombuffer(vec_row[0], dtype="float32")
                d_norm = float(np.linalg.norm(d_vec))
                if d_norm == 0.0:
                    sim = 0.0
                else:
                    sim = float(np.dot(q_unit, d_vec / d_norm))
            except Exception:
                sim = 0.0
            scored.append((sim, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [row for _, row in scored[:limit]]
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_doc_store.py -q
```

Expected: PASS (all tests — prior FTS5 tests + 3 new semantic tests). Semantic tests that use FakeEmbedder must all pass without fastembed.

- [ ] **Step 5: Run ruff**

```powershell
ruff check src/d365fo_agent/doc_store.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/d365fo_agent/doc_store.py tests/test_doc_store.py
git commit -m "feat: DocIndex.search hybrid path — FTS5 candidates + cosine rerank, degrades gracefully"
```

---

## Task 5: CLI — `--embed` flag on `build-doc-index` + `fetch-doc-vectors` command

**Files:**
- Modify: `src/d365fo_agent/cli.py`
- Test: `tests/test_doc_cli.py`

Two sub-tasks:

**5a — `--embed`:** after ingest, if `--embed` is passed and `EMBED_AVAILABLE` is True, call `di.add_vectors(get_embedder(), model_name=..., dim=384)` and include the vector count in the JSON output. If `EMBED_AVAILABLE` is False and `--embed` is passed, print a warning to stderr and continue (no error — graceful).

**5b — `fetch-doc-vectors`:** new command mirroring `fetch-knowledge` / `knowledge_fetch.fetch_knowledge`. Downloads a prebuilt `.db` or `.db.gz` vector asset and merges `chunk_vectors` rows into an existing `docs.db`. URL guard (http/https only). `.gz` decompressed on the fly. Stdlib only (`urllib`, `gzip`, `shutil`, `sqlite3`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_doc_cli.py`)

```python
import sys
import unittest

# EMBED_AVAILABLE for skip-guarding
try:
    from d365fo_agent.embed import EMBED_AVAILABLE
except ImportError:
    EMBED_AVAILABLE = False


# ---------------------------------------------------------------------------
# 5a: --embed flag
# ---------------------------------------------------------------------------
def test_build_doc_index_embed_flag_degrades_without_extra(tmp_path, capsys):
    """--embed with EMBED_AVAILABLE=False must warn but not crash; stats still valid."""
    import zipfile as zf
    from d365fo_agent.cli import main

    # Minimal docx
    WORD_XML = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr><w:r><w:t>X</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Some text here.</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    internal = tmp_path / "internal"
    internal.mkdir()
    with zf.ZipFile(internal / "x.docx", "w") as z:
        z.writestr("word/document.xml", WORD_XML)
    db = tmp_path / "docs.db"

    rc = main([
        "build-doc-index", "--db", str(db), "--internal", str(internal),
        "--embed",  # extra flag — must not crash even without fastembed
    ])
    # Always exits 0 — embed failure is non-fatal
    assert rc == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert "chunks_added" in out


# ---------------------------------------------------------------------------
# 5b: fetch-doc-vectors
# ---------------------------------------------------------------------------
def _make_vector_db(path):
    """Create a minimal docs.db-like file containing chunk_vectors rows."""
    import sqlite3
    import numpy as np

    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE chunk_vectors (chunk_id INTEGER, model TEXT, dim INTEGER, vector BLOB)"
    )
    blob = np.asarray([1.0, 0.0, 0.0], dtype="float32").tobytes()
    con.execute(
        "INSERT INTO chunk_vectors VALUES (1, 'intfloat/multilingual-e5-small', 3, ?)", (blob,)
    )
    con.commit()
    con.close()


def _fake_opener(asset_db_path):
    """Returns a callable that pretends to be urllib.request.urlopen for a file path."""
    def opener(url):
        import io
        return open(asset_db_path, "rb")
    return opener


def test_fetch_doc_vectors_merges_into_existing_db(tmp_path):
    """fetch-doc-vectors downloads an asset DB and merges chunk_vectors into docs.db."""
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy not available")

    import json
    from d365fo_agent.cli import main
    from d365fo_agent.doc_store import DocIndex
    from d365fo_agent.doc_ingest import Chunk

    # Build a docs.db with one chunk but no vectors.
    docs_db = tmp_path / "docs.db"
    with DocIndex(docs_db) as di:
        di.add_chunks([
            Chunk("d", "mslearn", "d365fo", "ap", "T", "https://x", 0, "T\nsome text")
        ])

    # Build a fake asset DB with a matching vector row.
    asset_db = tmp_path / "vectors.db"
    _make_vector_db(asset_db)

    # Invoke the CLI with a fake opener so no HTTP is attempted.
    # We patch knowledge_fetch.fetch_knowledge is NOT used here — fetch-doc-vectors
    # has its own inline logic.  We pass the asset path as --url and use monkeypatching
    # via the test-only --opener-path (or we rely on the fake_url trick using file://).
    # The cleanest approach: the command accepts "file://" URLs in test mode.
    import platform as _plat
    # Use a file:// URL — the implementation must strip the scheme and open directly.
    file_url = "https://example.com/vectors.db"  # guarded; we inject opener via import mock

    # Instead, we test the underlying helper directly since CLI I/O mocking is complex.
    from d365fo_agent.doc_vectors import fetch_doc_vectors

    result = fetch_doc_vectors(
        url=file_url,
        dest_db=docs_db,
        opener=_fake_opener(asset_db),
    )
    assert result["ok"] is True
    assert result["vectors_merged"] == 1

    # Verify the row landed in docs.db.
    import sqlite3
    con = sqlite3.connect(str(docs_db))
    count = con.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
    con.close()
    assert count == 1


def test_fetch_doc_vectors_rejects_non_http_url(tmp_path):
    """fetch-doc-vectors must reject non-http(s) URLs."""
    from d365fo_agent.doc_vectors import fetch_doc_vectors
    from d365fo_agent.doc_store import DocIndex

    docs_db = tmp_path / "docs.db"
    DocIndex(docs_db).close()

    result = fetch_doc_vectors(url="ftp://example.com/v.db", dest_db=docs_db)
    assert result["ok"] is False
    assert "http" in result["error"].lower()
```

> **Note on `fetch_doc_vectors`:** the helper is placed in a new thin module `src/d365fo_agent/doc_vectors.py` (not in `cli.py` or `knowledge_fetch.py`) so it can be unit-tested independently. The CLI `fetch-doc-vectors` command calls it.

- [ ] **Step 2: Run test to verify it fails**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_doc_cli.py -q -k "embed_flag or fetch_doc_vectors"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'd365fo_agent.doc_vectors'` and/or `SystemExit: 2` for unknown `--embed` flag.

- [ ] **Step 3a: Create `src/d365fo_agent/doc_vectors.py`** (new module)

```python
# src/d365fo_agent/doc_vectors.py
"""Download a prebuilt vector asset and merge ``chunk_vectors`` rows into an existing docs.db.

Mirrors ``knowledge_fetch.fetch_knowledge`` — stdlib only (``urllib``, ``gzip``, ``shutil``,
``sqlite3``).  Only http(s) URLs are accepted.  ``.gz`` assets are decompressed on the fly.

The asset is a SQLite file containing at minimum a ``chunk_vectors`` table with the same
schema as ``doc_store.DocIndex`` (``chunk_id, model, dim, vector BLOB``).  Rows are merged
with ``INSERT OR IGNORE`` so the operation is idempotent.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_DOC_VECTORS_URL: str | None = None  # Set when a prebuilt asset is published.


def _is_gzip(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(2) == b"\x1f\x8b"


def fetch_doc_vectors(
    url: str | None = None,
    dest_db: str | Path | None = None,
    *,
    force: bool = False,
    opener=urllib.request.urlopen,
) -> dict[str, object]:
    """Download a prebuilt vector asset and merge its ``chunk_vectors`` into ``dest_db``.

    Parameters
    ----------
    url:
        The http(s) URL to the asset ``.db`` or ``.db.gz``.  Defaults to
        ``DEFAULT_DOC_VECTORS_URL`` (currently unset — pass ``--url`` explicitly).
    dest_db:
        Path to the existing ``docs.db`` to merge into.  Required.
    force:
        Re-download even if the temp file already exists (always re-merges).
    opener:
        Injectable for testing (replaces ``urllib.request.urlopen``).

    Returns a result dict with ``ok`` (bool) and relevant metadata or ``error``.
    """
    effective_url = url or DEFAULT_DOC_VECTORS_URL
    if not effective_url:
        return {
            "ok": False,
            "error": (
                "No vector asset URL configured.  Pass --url <asset .db/.db.gz>, "
                "or build your own with: d365fo-agent build-doc-index --embed."
            ),
        }
    if not (effective_url.startswith("http://") or effective_url.startswith("https://")):
        return {"ok": False, "error": f"Refusing non-http(s) URL: {effective_url}"}

    if dest_db is None:
        return {"ok": False, "error": "dest_db is required."}
    dest_db = Path(dest_db)
    if not dest_db.exists():
        return {"ok": False, "error": f"Destination docs.db not found: {dest_db}"}

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_raw = Path(tmp_dir) / "vectors.part"
        tmp_db = Path(tmp_dir) / "vectors.db"

        # Download.
        with opener(effective_url) as response, open(tmp_raw, "wb") as out:  # noqa: S310
            shutil.copyfileobj(response, out)

        # Decompress if needed.
        if effective_url.endswith(".gz") or _is_gzip(tmp_raw):
            with gzip.open(tmp_raw, "rb") as gz, open(tmp_db, "wb") as out:
                shutil.copyfileobj(gz, out)
        else:
            shutil.copy(tmp_raw, tmp_db)

        # Merge chunk_vectors rows into dest_db.
        src = sqlite3.connect(str(tmp_db))
        dst = sqlite3.connect(str(dest_db))
        try:
            dst.execute(
                "CREATE TABLE IF NOT EXISTS chunk_vectors "
                "(chunk_id INTEGER, model TEXT, dim INTEGER, vector BLOB)"
            )
            # Add unique index to make INSERT OR IGNORE work correctly per (chunk_id, model).
            dst.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_cv_id_model "
                "ON chunk_vectors(chunk_id, model)"
            )
            rows = src.execute(
                "SELECT chunk_id, model, dim, vector FROM chunk_vectors"
            ).fetchall()
            dst.executemany(
                "INSERT OR IGNORE INTO chunk_vectors(chunk_id, model, dim, vector) VALUES (?,?,?,?)",
                rows,
            )
            dst.commit()
            merged = len(rows)
        finally:
            src.close()
            dst.close()

    return {
        "ok": True,
        "dest": str(dest_db),
        "vectors_merged": merged,
        "source": effective_url,
    }
```

- [ ] **Step 3b: Add `--embed` to `build-doc-index` dispatch** in `src/d365fo_agent/cli.py`

Locate the `build-doc-index` dispatch block (around line 221). After the `_dump_json({...})` call and **before** `return 0`, add:

```python
        if args.embed:
            from d365fo_agent.embed import EMBED_AVAILABLE
            if not EMBED_AVAILABLE:
                import warnings
                warnings.warn(
                    "build-doc-index --embed: the [semantic] extra is not installed. "
                    "Install it with: pip install d365fo-agent-developer[semantic]. "
                    "Skipping vector generation.",
                    stacklevel=1,
                )
            else:
                from d365fo_agent.embed import get_embedder
                embedder = get_embedder()
                n_vec = di.add_vectors(embedder, model_name="intfloat/multilingual-e5-small", dim=384)
                _dump_json({"vectors_added": n_vec, **di.stats()})
```

> IMPORTANT: The `_dump_json` and `return 0` that already exist in the block must be restructured so the stats JSON is printed only once (with or without vectors). Replace the existing `_dump_json({"db": ..., "chunks_added": added, **di.stats()})` line with:

```python
            result = {"db": str(db_path).replace("\\", "/"), "chunks_added": added, **di.stats()}
            if args.embed:
                from d365fo_agent.embed import EMBED_AVAILABLE
                if not EMBED_AVAILABLE:
                    import sys as _sys
                    print(
                        "WARNING: --embed requested but [semantic] extra is not installed. "
                        "Skipping vectors. Install with: pip install d365fo-agent-developer[semantic]",
                        file=_sys.stderr,
                    )
                else:
                    from d365fo_agent.embed import get_embedder
                    embedder = get_embedder()
                    n_vec = di.add_vectors(
                        embedder, model_name="intfloat/multilingual-e5-small", dim=384
                    )
                    result["vectors_added"] = n_vec
                    result.update(di.stats())
            _dump_json(result)
```

- [ ] **Step 3c: Add `--embed` to the `build-doc-index` subparser** in `_build_parser` (around line 577). After the last `build_doc.add_argument` line (`--rebuild`), add:

```python
    build_doc.add_argument(
        "--embed",
        action="store_true",
        help=(
            "After ingest, embed all chunks and store vectors in chunk_vectors. "
            "Requires the [semantic] extra: pip install d365fo-agent-developer[semantic]. "
            "Degrades gracefully if the extra is absent."
        ),
    )
```

- [ ] **Step 3d: Add `fetch-doc-vectors` dispatch** in `src/d365fo_agent/cli.py`. After the `build-doc-index` dispatch block (`return 0`) and before the `serve-mcp` block (around line 250), add:

```python
    if args.command == "fetch-doc-vectors":
        from d365fo_agent.doc_vectors import fetch_doc_vectors

        result = fetch_doc_vectors(
            url=args.url,
            dest_db=Path(args.db),
            force=args.force,
        )
        _dump_json(result)
        return 0 if result.get("ok") else 1
```

- [ ] **Step 3e: Add `fetch-doc-vectors` subparser** in `_build_parser`, immediately after the `build_doc` block (after its last `add_argument` call, before the `extract_aot`/`serve_mcp` block, around line 593):

```python
    fetch_doc_vectors_cmd = subparsers.add_parser(
        "fetch-doc-vectors",
        help=(
            "Download a prebuilt doc vector asset (.db or .db.gz) and merge "
            "chunk_vectors rows into an existing docs.db."
        ),
    )
    fetch_doc_vectors_cmd.add_argument(
        "--db", required=True,
        help="Path to the existing docs.db to merge vectors into.",
    )
    fetch_doc_vectors_cmd.add_argument(
        "--url",
        help=(
            "URL to the prebuilt vector asset (.db or .db.gz). "
            "Required (no default until an asset is published)."
        ),
    )
    fetch_doc_vectors_cmd.add_argument(
        "--force", action="store_true",
        help="Re-download and re-merge even if vectors are already present.",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_doc_cli.py -q
```

Expected: PASS (all prior + new tests). The `--embed` degrade test must pass without fastembed installed.

- [ ] **Step 5: Run ruff**

```powershell
ruff check src/d365fo_agent/doc_vectors.py src/d365fo_agent/cli.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/d365fo_agent/doc_vectors.py src/d365fo_agent/cli.py tests/test_doc_cli.py
git commit -m "feat: --embed flag for build-doc-index; fetch-doc-vectors command + doc_vectors module"
```

---

## Task 6: MCP `search_docs` — optional `semantic` boolean arg

**Files:**
- Modify: `src/d365fo_agent/mcp_server.py`
- Test: `tests/test_doc_mcp_tools.py`

Add `semantic` (boolean, optional, default `true`) to the `search_docs` tool schema. At runtime: if `semantic=true` AND `EMBED_AVAILABLE` AND vectors are present in the index, pass `semantic=True` + a fresh `get_embedder()` to `DocIndex.search`. Otherwise fall back to FTS5 silently. The tool description is updated to mention the hybrid mode.

- [ ] **Step 1: Write the failing test** (append to `tests/test_doc_mcp_tools.py`)

```python
def test_search_docs_semantic_false_always_works(tmp_path):
    """semantic=False must produce FTS5 results regardless of vector presence."""
    server = _server_with_docs(tmp_path)
    out = _call(server, "search_docs", {"query": "settlement payments", "semantic": False})
    assert out["found"] is True
    assert out["results"]


def test_search_docs_semantic_true_degrades_without_extra(tmp_path, monkeypatch):
    """semantic=True must fall back to FTS5 when EMBED_AVAILABLE is False."""
    import d365fo_agent.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EMBED_AVAILABLE", False)

    server = _server_with_docs(tmp_path)
    out = _call(server, "search_docs", {"query": "settlement payments", "semantic": True})
    # Must still return results (FTS5 fallback), not an error.
    assert out["found"] is True
    assert out["results"]


def test_search_docs_tool_schema_has_semantic_field(tmp_path):
    """The search_docs tool schema must include a 'semantic' boolean property."""
    server = _server_with_docs(tmp_path)
    search_tool = server.tools["search_docs"]  # server stores tools in a dict, no list_tools()
    props = search_tool["inputSchema"]["properties"]
    assert "semantic" in props, "search_docs schema must expose 'semantic' boolean arg"
    assert props["semantic"].get("type") == "boolean"
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_doc_mcp_tools.py -q -k "semantic"
```

Expected: FAIL — `AssertionError: search_docs schema must expose 'semantic' boolean arg` (or KeyError).

- [ ] **Step 3: Edit `search_docs` in `src/d365fo_agent/mcp_server.py`**

Locate the `search_docs` `@tool(...)` call inside `_register_tools` (around line 770). Make two targeted edits:

**3a — Update the description string** (replace the existing description literal):

```python
            "Search the INGESTED D365 functional documentation (MS Learn + internal specs) for "
            "prose that grounds a FUNCTIONAL question — e.g. 'how does vendor invoice matching work'. "
            "Use this to ground functional behaviour BEFORE writing it from memory; every hit carries "
            "its source citation (source_ref). Complements the AOT/symbol tools (which ground "
            "technical facts). Returns ranked chunks with a snippet, not full pages. "
            "Set semantic=true (default) to use hybrid BM25→cosine rerank when the [semantic] "
            "extra is installed and vectors are present; degrades silently to FTS5 otherwise.",
```

**3b — Add `semantic` to the tool schema properties** (replace the existing `properties` dict):

```python
            {"type": "object", "properties": {
                "query": STR, "platform": STR, "module": STR, "origin": STR,
                "limit": INT, "semantic": BOOL,
            }, "required": ["query"]},
```

**3c — Update the handler body** (replace the existing `search_docs` function body):

```python
        def search_docs(args: dict[str, Any]) -> dict[str, Any]:
            di = self._doc_index_if_ready()
            if di is None:
                return {"found": False, "error": _NO_DOCS}
            use_semantic = bool(args.get("semantic", True))
            embedder = None
            model_name = "intfloat/multilingual-e5-small"
            if use_semantic:
                try:
                    from d365fo_agent.embed import EMBED_AVAILABLE, get_embedder
                    if EMBED_AVAILABLE:
                        embedder = get_embedder(model_name)
                except Exception:
                    pass  # degrade to FTS5 on any import/init failure
            return {"found": True, "results": di.search(
                args["query"],
                platform=args.get("platform"),
                module=args.get("module"),
                origin=args.get("origin"),
                limit=int(args.get("limit", 10)),
                semantic=use_semantic,
                embedder=embedder,
                model_name=model_name,
            )}
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
$env:PYTHONPATH='src'; pytest tests/test_doc_mcp_tools.py -q
```

Expected: PASS (all prior tests + 3 new).

- [ ] **Step 5: Run the full suite to confirm no regressions**

```powershell
$env:PYTHONPATH='src'; pytest -q
```

Expected: all tests pass; semantic tests are NOT skipped (they use the FakeEmbedder or monkeypatching — no real fastembed needed).

- [ ] **Step 6: Run ruff**

```powershell
ruff check src/d365fo_agent/mcp_server.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/d365fo_agent/mcp_server.py tests/test_doc_mcp_tools.py
git commit -m "feat: search_docs MCP tool — optional semantic boolean arg, hybrid rerank, graceful FTS5 fallback"
```

---

## Task 7: Docs + full-suite gate + ruff

**Files:**
- Modify: `README.md`
- Modify: `docs/mcp-server.md`

- [ ] **Step 1: Update `README.md`** — add a "Semantic search (optional)" sub-section under the existing "Functional documentation grounding" section:

```markdown
#### Semantic search (optional)

Install the `[semantic]` extra to enable hybrid BM25 → cosine-rerank search:

```bash
pip install d365fo-agent-developer[semantic]
```

This downloads and caches `intfloat/multilingual-e5-small` (ONNX, ~120 MB) on first use.
The model is multilingual (French + English).

**Embed your corpus after indexing:**

```bash
d365fo-agent build-doc-index \
  --db .omx/index/docs.db \
  --internal <docx-folder> \
  [--mslearn <clone>] \
  --embed          # ← computes and stores vectors
```

Or download a prebuilt vector asset (when published):

```bash
d365fo-agent fetch-doc-vectors \
  --db .omx/index/docs.db \
  --url https://github.com/dbru540/d365fo-agent-developer/releases/download/doc-vectors-v1/doc-vectors.db.gz
```

**Without the extra**, the server automatically falls back to FTS5 full-text search — no configuration change needed.
```

- [ ] **Step 2: Update `docs/mcp-server.md`** — add a note to the `search_docs` tool entry:

```markdown
#### `search_docs`

…existing description…

**`semantic` (boolean, optional, default `true`):** when `true` and the `[semantic]` extra
is installed and vectors are present in the index, uses hybrid BM25 → cosine-rerank for
better multilingual recall. Degrades silently to FTS5 when the extra is absent or vectors
are not yet computed. Set to `false` to force FTS5-only (faster, always available).

The underlying model is `intfloat/multilingual-e5-small` (dim 384). Documents and queries
are prefixed (`"passage: "` / `"query: "`) as required by the e5 model family.

**Prebuilt vectors:** use `fetch-doc-vectors` to download a vector asset; or embed locally
with `build-doc-index --embed`. Both are optional — the index ships as FTS5-first.
```

- [ ] **Step 3: Run the FULL test suite**

```powershell
$env:PYTHONPATH='src'; pytest -q
```

Expected: ALL tests pass. Semantic tests that use `FakeEmbedder` or `monkeypatch` pass without fastembed. Tests guarded by `@unittest.skipUnless(EMBED_AVAILABLE, ...)` are skipped (zero failures — skips are expected).

- [ ] **Step 4: Run ruff across all modified modules**

```powershell
ruff check src/d365fo_agent/embed.py src/d365fo_agent/doc_store.py src/d365fo_agent/doc_vectors.py src/d365fo_agent/mcp_server.py src/d365fo_agent/cli.py
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/mcp-server.md
git commit -m "docs: note [semantic] extra, e5 model, --embed, fetch-doc-vectors, FTS5 degradation"
```

---

## Self-Review

### 1. Spec coverage vs design Phase 2 (§4 / §2)

| Design decision | Plan coverage |
|---|---|
| `[semantic]` optional extra, `fastembed`, ONNX, no torch | Task 1 (`pyproject`) + Task 2 (`embed.py`) |
| `EMBED_AVAILABLE` flag + lazy import + graceful FTS5 degrade | Task 2 (`embed.py`), Tasks 4/6 (degrade tests) |
| Model `intfloat/multilingual-e5-small`, dim 384, MEAN, normalization | Task 2 `get_embedder` / `_register_model` |
| `add_custom_model` double-registration guard (`try/except`) | Task 2 `_register_model` implementation |
| e5 prefix `"passage: "` for documents, `"query: "` for queries | Task 2 `embed_passages` / `embed_query` + prefix tests |
| blob encoding `np.asarray(v, dtype="float32").tobytes()` | Task 2 `vector_to_blob` / `blob_to_vector` + round-trip test |
| `chunk_vectors(chunk_id, model, dim, vector BLOB)` already created | Task 3 uses existing table — no migration needed |
| `add_vectors(embedder)` — populate chunk_vectors, idempotent | Task 3 |
| Hybrid search: FTS5 top-N candidates → cosine rerank | Task 4 |
| Degrade to FTS5 when vectors absent or embedder None | Task 4 `test_search_semantic_degrades_without_vectors` |
| FTS5 `semantic=False` path unchanged | Task 4 `test_search_semantic_false_unchanged` |
| `build-doc-index --embed` CLI flag | Task 5a |
| `fetch-doc-vectors` CLI command (mirrors `knowledge_fetch`) | Task 5b + `doc_vectors.py` |
| URL guard http/https | Task 5 `doc_vectors.fetch_doc_vectors` + test |
| `.gz` decompression | Task 5 `doc_vectors._is_gzip` + `gzip.open` |
| MCP `search_docs` optional `semantic` boolean arg | Task 6 |
| Tool degrades to FTS5 when extra absent | Task 6 `monkeypatch` test |
| Tool description updated to mention hybrid mode | Task 6 Step 3a |
| README + docs/mcp-server.md updated | Task 7 |
| Tests run green WITHOUT extra (semantic tests skip or use fakes) | Tasks 2–6 skip guards + `FakeEmbedder` pattern |
| Prebuilt asset download deferred (no real corpus embedding in plan) | Explicitly noted as out-of-scope; `DEFAULT_DOC_VECTORS_URL = None` |

### 2. Placeholder scan

Every implementation step contains complete, runnable code. No TBD, TODO, or ellipsis placeholders appear in code blocks. The only deferred item is the real prebuilt asset URL (`DEFAULT_DOC_VECTORS_URL = None`) — intentional per scope decision.

### 3. Type consistency

- `embed_passages(texts: list[str]) -> list[bytes]` — Task 2 interface + Task 3 `add_vectors` calls `embedder.embed(list[str])` (matches `FakeEmbedder.embed` and fastembed's `TextEmbedding.embed`).
- `add_vectors(embedder, *, model_name: str, dim: int) -> int` — called identically in CLI (`doc_vectors`), tests, and MCP server.
- `DocIndex.search(..., semantic=False, embedder=None, model_name=...) -> list[dict]` — keyword-only additions; positional call sites in existing tests remain valid.
- `fetch_doc_vectors(url, dest_db, *, force, opener) -> dict` — called by CLI and tests consistently.
- `cosine(a_blob: bytes, b_blob: bytes) -> float` — used only in `embed.py` tests; `doc_store.search` inlines the numpy dot-product to avoid the import overhead per-candidate.

### 4. FakeEmbedder coverage

`FakeEmbedder` (defined in `tests/test_doc_store.py`) maps `"settlement" → [1,0,0]`, `"reconciliation" → [0,1,0]`, `"journal" → [0,0,1]`. The hybrid rerank test uses a chunk containing only `"reconciliation"` vs one containing both — the cosine similarity against the `"reconciliation"` query vector `[0,1,0]` deterministically ranks the pure chunk first, providing a meaningful (not trivially vacuous) rerank assertion.

### 5. Concern: fastembed `add_custom_model` API stability

The `add_custom_model` call uses `fastembed.common.model_description.PoolingType` and `ModelSource`. These are internal fastembed classes confirmed correct for the fastembed version available at design time (2026-06-23). If a future fastembed version renames these, `_register_model` will raise — the `try/except Exception: pass` guard in `_register_model` will silently skip registration (the model may already be built-in by then). This is acceptable given the deferred real-model-download scope.
