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
