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
        assert first["title"] == "T"
        assert first["text"] == "settlement matches invoices and payments"
        assert first["source_ref"] == "https://learn/x"
        assert di.get(999) is None


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


# ---------------------------------------------------------------------------
# Fake embedder — deterministic, no fastembed or numpy needed.
# Maps text fragments to fixed small float lists (dim 3 for speed).
# ---------------------------------------------------------------------------
class FakeEmbedder:
    """Deterministic in-test embedder that maps known text substrings to fixed vectors.

    embed(texts) accepts a list of prefixed strings (e.g. "passage: settlement …") and
    returns a generator of plain Python lists — no numpy, no fastembed.
    Unknown texts get a zero vector.
    """

    _MAP = {
        "settlement": [1.0, 0.0, 0.0],
        "reconciliation": [0.0, 1.0, 0.0],
        "journal": [0.0, 0.0, 1.0],
    }
    _DIM = 3

    def embed(self, texts):
        for text in texts:
            t = text.lower()
            vec = next((v for key, v in self._MAP.items() if key in t), [0.0] * self._DIM)
            yield list(vec)


def _make_index_with_chunks(tmp_path):
    """Helper: DocIndex with three chunks and no vectors yet."""
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


# ---------------------------------------------------------------------------
# Task 4 — hybrid semantic search tests
# ---------------------------------------------------------------------------

def test_search_semantic_reranks_candidates(tmp_path):
    """Hybrid search must reorder results by cosine similarity, not BM25.

    FakeEmbedder maps:
      "settlement" -> [1, 0, 0]
      "reconciliation" -> [0, 1, 0]
      "journal" -> [0, 0, 1]
    The query "reconciliation" maps to [0, 1, 0].
    After FTS5 top-N we rerank by cosine: the reconciliation chunk must rank first,
    even if BM25 would rank it second.
    """
    di = DocIndex(tmp_path / "docs.db")
    # Add chunks in an order where FTS5 might rank "settlement" higher on a multi-keyword query.
    di.add_chunks([
        _chunk("settlement reconciliation vendor payments", ord=0, module="ap"),  # id=1 - contains both
        _chunk("bank reconciliation statement monthly", ord=1, module="gl"),       # id=2 - pure reconciliation
        _chunk("general ledger journal posting entries", ord=2, module="gl"),      # id=3 - unrelated
    ])
    embedder = FakeEmbedder()
    di.add_vectors(embedder, model_name="fake/dim3", dim=3)

    # Semantic query for "reconciliation" -> vector [0,1,0]
    results = di.search("reconciliation", semantic=True, embedder=embedder,
                        model_name="fake/dim3")
    assert results, "expected at least one result"
    # The pure reconciliation chunk (id=2) should rank above the mixed one (id=1).
    ids = [r["id"] for r in results]
    assert ids.index(2) < ids.index(1), (
        f"Expected id=2 before id=1 in semantic rerank; got order {ids}"
    )
    di.close()


def test_search_semantic_uses_or_recall_for_disjoint_terms(tmp_path):
    """Hybrid search must retrieve candidates with OR-recall, not AND-of-all-terms.

    No single chunk contains BOTH 'settlement' and 'journal', so the old AND-gated
    retrieval returned zero candidates and the semantic layer had nothing to rerank.
    OR-recall retrieves both; cosine rerank then surfaces the best match.
    """
    di = DocIndex(tmp_path / "docs.db")
    di.add_chunks([
        _chunk("settlement matches vendor invoices", ord=0, module="ap"),        # id=1 -> [1,0,0]
        _chunk("general ledger journal posting entries", ord=1, module="gl"),     # id=2 -> [0,0,1]
    ])
    embedder = FakeEmbedder()
    di.add_vectors(embedder, model_name="fake/dim3", dim=3)

    # Two terms that never co-occur in one chunk; AND-gating -> 0 candidates.
    results = di.search("settlement journal", semantic=True, embedder=embedder,
                        model_name="fake/dim3")
    assert results, "OR-recall must retrieve candidates even when no chunk holds all terms"
    # FakeEmbedder maps the query 'settlement journal' to [1,0,0], so id=1 wins the rerank.
    assert results[0]["id"] == 1, f"expected id=1 first, got {[r['id'] for r in results]}"
    di.close()


def test_search_semantic_degrades_without_vectors(tmp_path):
    """When no vectors are present, semantic=True falls back to FTS5 silently."""
    di = DocIndex(tmp_path / "docs.db")
    di.add_chunks([_chunk("settlement reconciliation", ord=0)])
    # No add_vectors call - has_vectors is False.
    results = di.search("settlement", semantic=True, embedder=FakeEmbedder(),
                        model_name="fake/dim3")
    assert results  # FTS5 fallback still returns results
    di.close()


def test_search_semantic_false_unchanged(tmp_path):
    """semantic=False (default) must produce the same results as before this task."""
    di = DocIndex(tmp_path / "docs.db")
    di.add_chunks([_chunk("settlement matches vendor invoices", ord=0)])
    results = di.search("settlement")
    assert results[0]["id"] == 1
    di.close()
