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
