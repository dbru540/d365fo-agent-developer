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


def test_search_docs_tool_schema_has_semantic_field(tmp_path):
    """The search_docs tool schema must include a 'semantic' boolean property."""
    server = _server_with_docs(tmp_path)
    search_tool = server.tools["search_docs"]
    props = search_tool["inputSchema"]["properties"]
    assert "semantic" in props, "search_docs schema must expose 'semantic' boolean arg"
    assert props["semantic"].get("type") == "boolean"
