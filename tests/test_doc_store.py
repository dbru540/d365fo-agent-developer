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
