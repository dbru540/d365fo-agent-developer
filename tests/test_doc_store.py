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
