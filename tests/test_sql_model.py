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
    CREATE TABLE unit_interfaces(unit_a TEXT, unit_b TEXT, n_views INTEGER, examples TEXT);
    CREATE TABLE sql_unique_index_columns(table_name TEXT, index_name TEXT, column_name TEXT, key_ordinal INTEGER);
    CREATE TABLE sql_table_rowcounts(table_name TEXT, row_count INTEGER);
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
    # Second table + a payment-side view that also reads CUSTTRANSOPEN — gives find_relations
    # a shared view (table-table) and a cross-unit pair (view-view).
    conn.execute("INSERT INTO sql_tables VALUES(11,'CUSTTRANSOPEN','2024-01-01','2024-01-01')")
    conn.execute("INSERT INTO sql_table_columns VALUES(11,1,'RECID','bigint',8,19,0,0)")
    conn.execute("INSERT INTO sql_views VALUES(2,'dbo','CUSTPAYMENTENTITY','2024-01-01','2024-01-01',"
                 "'CREATE VIEW CUSTPAYMENTENTITY AS SELECT ... FROM CUSTTRANSOPEN ...')")
    conn.execute("INSERT INTO sql_view_columns VALUES(2,1,'PAYMENTAMOUNT','numeric',17,32,6,0)")
    conn.execute("INSERT INTO view_model VALUES(2,'CUSTPAYMENTENTITY','entity','CustPaymentEntity','standard',1,1,0)")
    conn.execute("INSERT INTO model_view_tables VALUES(2,'CUSTPAYMENTENTITY','CUSTTRANSOPEN','direct')")
    conn.execute("INSERT INTO functional_views VALUES('CUSTPAYMENTENTITY','paiement',2)")
    conn.execute("INSERT INTO unit_interfaces VALUES('lettrage-reglement','paiement',12,'CUSTPAYMENTENTITY')")
    conn.executemany("INSERT INTO sql_unique_index_columns VALUES(?,?,?,?)", [
        ("CUSTSETTLEMENT", "I_SETTLEKEY", "DATAAREAID", 1),
        ("CUSTSETTLEMENT", "I_SETTLEKEY", "TRANSRECID", 2),
    ])
    conn.execute("INSERT INTO sql_table_rowcounts VALUES('CUSTSETTLEMENT', 42000)")
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
        self.assertEqual(result["alternate_keys"],
                         [{"index": "I_SETTLEKEY", "columns": ["DATAAREAID", "TRANSRECID"]}])
        self.assertEqual(result["row_count"], 42000)

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

    def test_explore_functional_unit(self) -> None:
        from d365fo_agent.sql_model import explore_functional_unit

        result = explore_functional_unit(self.db, "lettrage-reglement")
        self.assertTrue(result["found"])
        self.assertEqual(result["n_tables"], 2)
        core = {t["table"] for t in result["core_tables"]}
        self.assertEqual(core, {"CUSTSETTLEMENT", "CUSTTRANSOPEN"})
        self.assertIn("CUSTSETTLEMENTENTITY", result["entities"])
        iface = result["interfaces"][0]
        self.assertEqual(iface["with"], "paiement")
        self.assertEqual(iface["bridge_views"], 12)

    def test_explore_unknown_unit_suggests(self) -> None:
        from d365fo_agent.sql_model import explore_functional_unit

        result = explore_functional_unit(self.db, "lettrage")
        self.assertFalse(result["found"])
        self.assertIn("lettrage-reglement", result["suggestions"])

    def test_find_relations_table_table(self) -> None:
        from d365fo_agent.sql_model import find_relations

        result = find_relations(self.db, "CUSTSETTLEMENT", "CUSTTRANSOPEN")
        self.assertTrue(result["found"])
        self.assertEqual(result["relation"], "joined_by_views")
        self.assertIn("CUSTSETTLEMENTENTITY", result["joining_views"])
        self.assertEqual(result["joining_view_count"], 1)

    def test_find_relations_view_view_cross_unit(self) -> None:
        from d365fo_agent.sql_model import find_relations

        result = find_relations(self.db, "CUSTSETTLEMENTENTITY", "CUSTPAYMENTENTITY")
        self.assertTrue(result["found"])
        self.assertEqual(result["relation"], "share_base_tables")
        self.assertEqual([t["table"] for t in result["shared_tables"]], ["CUSTTRANSOPEN"])
        self.assertEqual(result["unit_interface"]["bridge_views"], 12)

    def test_find_relations_view_table(self) -> None:
        from d365fo_agent.sql_model import find_relations

        result = find_relations(self.db, "CUSTPAYMENTENTITY", "custtransopen")
        self.assertEqual(result["relation"], "view_reads_table")
        self.assertEqual(result["via"], ["direct"])
        result2 = find_relations(self.db, "CUSTPAYMENTENTITY", "CUSTSETTLEMENT")
        self.assertEqual(result2["relation"], "no_direct_dependency")

    def test_mcp_functional_tools_registered(self) -> None:
        from d365fo_agent.index_store import D365Index
        from d365fo_agent.mcp_server import build_server_from_config

        kdb = self.root / "k2.db"
        D365Index(kdb).close()
        srv = build_server_from_config(db_path=kdb, sql_model_path=self.db)
        try:
            self.assertIn("explore_functional_unit", srv.tools)
            self.assertIn("find_relations", srv.tools)
            response = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "explore_functional_unit",
                           "arguments": {"unit": "lettrage-reglement"}}})
            payload = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(payload["found"])
        finally:
            if srv._index is not None:
                srv._index.close()

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
