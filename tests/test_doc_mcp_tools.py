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


# ---------------------------------------------------------------------------
# Task 6: semantic boolean arg on search_docs
# ---------------------------------------------------------------------------
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


def test_search_docs_semantic_or_recall_end_to_end(tmp_path, monkeypatch):
    """End-to-end: search_docs (semantic default) routes NL queries through OR-recall.

    The query 'settlement journal' has two terms that never co-occur in one chunk, so the
    old AND-gating returned 0 results. With vectors present and an embedder available, the
    tool must OR-recall the candidates and cosine-rerank to a cited hit.
    """
    class _Fake:
        _MAP = {"settlement": [1.0, 0.0, 0.0], "journal": [0.0, 0.0, 1.0]}

        def embed(self, texts):
            for t in texts:
                tl = t.lower()
                yield list(next((v for k, v in self._MAP.items() if k in tl), [0.0, 0.0, 0.0]))

    db = tmp_path / "docs.db"
    model = "intfloat/multilingual-e5-small"
    with DocIndex(db) as di:
        di.add_chunks([
            Chunk("d", "mslearn", "d365fo", "ap", "Settlement",
                  "https://learn/x/settlement", 0, "Settlement matches vendor invoices."),
            Chunk("d", "mslearn", "d365fo", "gl", "Journal",
                  "https://learn/x/journal", 1, "General ledger journal posting entries."),
        ])
        di.add_vectors(_Fake(), model_name=model, dim=3)

    import d365fo_agent.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EMBED_AVAILABLE", True)
    monkeypatch.setattr(embed_mod, "get_embedder", lambda *a, **k: _Fake())

    server = build_server_from_config(db_path=tmp_path / "none.db", doc_db_path=db)
    out = _call(server, "search_docs", {"query": "settlement journal"})  # semantic defaults to True
    assert out["found"] is True
    assert out["results"], "OR-recall via search_docs must return hits for a disjoint-term NL query"
    assert out["results"][0]["source_ref"] == "https://learn/x/settlement"


def test_search_docs_tool_schema_has_semantic_field(tmp_path):
    """The search_docs tool schema must include a 'semantic' boolean property."""
    server = _server_with_docs(tmp_path)
    search_tool = server.tools["search_docs"]
    props = search_tool["inputSchema"]["properties"]
    assert "semantic" in props, "search_docs schema must expose 'semantic' boolean arg"
    assert props["semantic"].get("type") == "boolean"
