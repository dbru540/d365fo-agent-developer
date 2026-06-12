import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from uuid import uuid4

from test_catalog import TEST_TEMP_ROOT


def create_sql_model_fixture(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE sql_views(object_id INTEGER PRIMARY KEY, schema_name TEXT, name TEXT,
        create_date TEXT, modify_date TEXT, definition TEXT);
    CREATE TABLE sql_view_columns(object_id INTEGER, column_id INTEGER, name TEXT, type TEXT,
        max_length INTEGER, precision INTEGER, scale INTEGER, is_nullable INTEGER);
    CREATE TABLE sql_tables(object_id INTEGER PRIMARY KEY, name TEXT, create_date TEXT, modify_date TEXT);
    CREATE TABLE sql_table_columns(object_id INTEGER, column_id INTEGER, name TEXT, type TEXT,
        max_length INTEGER, precision INTEGER, scale INTEGER, is_nullable INTEGER);
    CREATE TABLE sql_pk_columns(object_id INTEGER, table_name TEXT, index_name TEXT,
        column_name TEXT, key_ordinal INTEGER);
    CREATE TABLE view_model(object_id INTEGER, name TEXT, kind TEXT, aot_name TEXT,
        aot_source TEXT, n_columns INTEGER, n_tables INTEGER, n_views_ref INTEGER);
    CREATE TABLE model_view_tables(referencing_id INTEGER, view_name TEXT, table_name TEXT, via TEXT);
    CREATE TABLE functional_units(table_name TEXT PRIMARY KEY, unit TEXT, how TEXT);
    CREATE TABLE functional_views(view_name TEXT PRIMARY KEY, unit TEXT, units_spanned INTEGER);
    """)
    conn.execute("INSERT INTO sql_views VALUES(1,'dbo','CUSTSETTLEMENTENTITY','2024-01-01','2024-01-01',"
                 "'CREATE VIEW CUSTSETTLEMENTENTITY AS SELECT ... FROM CUSTSETTLEMENT JOIN CUSTTRANSOPEN ...')")
    conn.executemany("INSERT INTO sql_view_columns VALUES(?,?,?,?,?,?,?,?)", [
        (1, 1, "SETTLEMENTAMOUNT", "numeric", 17, 32, 6, 0),
        (1, 2, "TRANSDATE", "datetime", 8, 23, 3, 0),
    ])
    conn.execute("INSERT INTO sql_tables VALUES(10,'CUSTSETTLEMENT','2024-01-01','2024-01-01')")
    conn.executemany("INSERT INTO sql_table_columns VALUES(?,?,?,?,?,?,?,?)", [
        (10, 1, "RECID", "bigint", 8, 19, 0, 0),
        (10, 2, "SETTLEDCUR", "numeric", 17, 32, 6, 0),
    ])
    conn.execute("INSERT INTO sql_pk_columns VALUES(10,'CUSTSETTLEMENT','I_RECID','RECID',1)")
    conn.execute("INSERT INTO view_model VALUES(1,'CUSTSETTLEMENTENTITY','entity','CustSettlementEntity','standard',2,2,0)")
    conn.executemany("INSERT INTO model_view_tables VALUES(?,?,?,?)", [
        (1, "CUSTSETTLEMENTENTITY", "CUSTSETTLEMENT", "direct"),
        (1, "CUSTSETTLEMENTENTITY", "CUSTTRANSOPEN", "direct"),
    ])
    conn.executemany("INSERT INTO functional_units VALUES(?,?,?)", [
        ("CUSTSETTLEMENT", "lettrage-reglement", "prefix"),
        ("CUSTTRANSOPEN", "lettrage-reglement", "prefix"),
    ])
    conn.execute("INSERT INTO functional_views VALUES('CUSTSETTLEMENTENTITY','lettrage-reglement',1)")
    conn.commit()
    conn.close()


class SqlModelTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "sqlmodel.db"
        create_sql_model_fixture(self.db)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_entity_view_lookup(self) -> None:
        from d365fo_agent.sql_model import get_sql_model

        result = get_sql_model(self.db, "CustSettlementEntity")  # case-insensitive
        self.assertTrue(result["found"])
        self.assertEqual(result["object"], "view")
        self.assertEqual(result["kind"], "entity")
        self.assertEqual(result["functional_unit"], "lettrage-reglement")
        self.assertEqual([c["name"] for c in result["columns"]], ["SETTLEMENTAMOUNT", "TRANSDATE"])
        tables = {t["table"]: t["unit"] for t in result["base_tables"]}
        self.assertEqual(tables, {"CUSTSETTLEMENT": "lettrage-reglement",
                                  "CUSTTRANSOPEN": "lettrage-reglement"})
        self.assertNotIn("definition", result)

    def test_definition_included_on_request(self) -> None:
        from d365fo_agent.sql_model import get_sql_model

        result = get_sql_model(self.db, "CUSTSETTLEMENTENTITY", include_definition=True)
        self.assertIn("CREATE VIEW", result["definition"])
        self.assertFalse(result["definition_truncated"])

    def test_table_lookup_with_pk_and_referencing_views(self) -> None:
        from d365fo_agent.sql_model import get_sql_model

        result = get_sql_model(self.db, "custsettlement")
        self.assertTrue(result["found"])
        self.assertEqual(result["object"], "table")
        self.assertEqual(result["primary_key"], ["RECID"])
        self.assertEqual(result["functional_unit"], "lettrage-reglement")
        self.assertIn("CUSTSETTLEMENTENTITY", result["referenced_by_views"])

    def test_not_found_gives_suggestions(self) -> None:
        from d365fo_agent.sql_model import get_sql_model

        result = get_sql_model(self.db, "CustSett")  # prefix of sibling views
        self.assertFalse(result["found"])
        self.assertIn("CUSTSETTLEMENTENTITY", result["suggestions"])

    def test_degrades_without_analysis_tables(self) -> None:
        from d365fo_agent.sql_model import get_sql_model

        conn = sqlite3.connect(self.db)
        conn.executescript("DROP TABLE view_model; DROP TABLE functional_units; "
                           "DROP TABLE functional_views; DROP TABLE model_view_tables;")
        conn.commit()
        conn.close()
        result = get_sql_model(self.db, "CUSTSETTLEMENTENTITY")
        self.assertTrue(result["found"])
        self.assertNotIn("functional_unit", result)

    def test_mcp_tool_with_and_without_model(self) -> None:
        from d365fo_agent.mcp_server import build_server_from_config

        def call(server, args):
            response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "get_sql_model", "arguments": args}})
            return json.loads(response["result"]["content"][0]["text"])

        # Knowledge index fixture: reuse the sql model db path trick is not possible — build a tiny index.
        from d365fo_agent.index_store import D365Index
        kdb = self.root / "k.db"
        D365Index(kdb).close()

        srv = build_server_from_config(db_path=kdb, sql_model_path=self.db)
        try:
            payload = call(srv, {"name": "CUSTSETTLEMENTENTITY"})
            self.assertTrue(payload["found"])
            self.assertEqual(payload["functional_unit"], "lettrage-reglement")
        finally:
            if srv._index is not None:
                srv._index.close()

        srv2 = build_server_from_config(db_path=kdb)
        try:
            payload = call(srv2, {"name": "CUSTSETTLEMENTENTITY"})
            self.assertFalse(payload["found"])
            self.assertIn("No SQL model configured", payload["error"])
        finally:
            if srv2._index is not None:
                srv2._index.close()


if __name__ == "__main__":
    unittest.main()
