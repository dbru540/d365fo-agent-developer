"""Tests for the operational MCP layer: SQLite index, knowledge queries, validation, server."""

import json
import shutil
import unittest
from uuid import uuid4

from test_catalog import RULES_JSON, TEST_TEMP_ROOT, create_fixture_repo


class IndexStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo_root = create_fixture_repo(self.root)
        self.rules_path = self.root / "rules.json"
        self.rules_path.write_text(json.dumps(RULES_JSON), encoding="utf-8")
        self.db_path = self.root / "i.db"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _catalog(self):
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.rules import load_rules

        return build_catalog(self.repo_root, load_rules(self.rules_path))

    def test_build_and_query_custom_index(self) -> None:
        from d365fo_agent.index_store import D365Index

        with D365Index(self.db_path) as index:
            stats = index.build_from_catalog(self._catalog())
            self.assertEqual(stats["artifacts_custom"], 5)
            self.assertGreater(stats["relations"], 0)
            self.assertTrue(index.exists("BABBFCAccount"))
            self.assertTrue(index.exists("BABBFCAccount", "AxSecurityPrivilege"))
            self.assertFalse(index.exists("NoSuchElement999"))
            matches = index.lookup_exact("BABAssetTable_Extension")
            self.assertEqual(matches[0]["artifact_type"], "AxClass")

    def test_search_finds_by_token(self) -> None:
        from d365fo_agent.index_store import D365Index

        with D365Index(self.db_path) as index:
            index.build_from_catalog(self._catalog())
            results = index.search("BABBFCAccount")
            self.assertTrue(any(r["name"] == "BABBFCAccount" for r in results))

    def test_relations_and_neighbors(self) -> None:
        from d365fo_agent.index_store import D365Index

        with D365Index(self.db_path) as index:
            index.build_from_catalog(self._catalog())
            rels = index.relations_of("AssetTable.BABAccountsPayable")
            self.assertTrue(any(r["relation_type"] == "extension-of" for r in rels))
            self.assertIn("AssetTable", index.neighbors("AssetTable.BABAccountsPayable"))

    def test_index_packages_local_handles_multi_model_layout(self) -> None:
        from d365fo_agent.index_store import D365Index

        # Build a fake PackagesLocalDirectory with single- and multi-model packages.
        pkg_root = self.root / "PackagesLocalDirectory"
        single = pkg_root / "SinglePkg" / "SinglePkg" / "AxClass"
        single.mkdir(parents=True)
        (single / "FooClass.xml").write_text("<AxClass><Name>FooClass</Name></AxClass>", encoding="utf-8")
        multi = pkg_root / "BigPkg" / "ModelA" / "AxTable"
        multi.mkdir(parents=True)
        (multi / "BarTable.xml").write_text("<AxTable><Name>BarTable</Name></AxTable>", encoding="utf-8")

        with D365Index(self.db_path) as index:
            result = index.index_packages_local(pkg_root)
            self.assertGreaterEqual(result["artifacts_added"], 2)
            # The multi-model element (model name != package name) must be indexed.
            self.assertTrue(index.exists("BarTable", "AxTable"))
            self.assertTrue(index.exists("FooClass", "AxClass"))
            bar = index.lookup_exact("BarTable")[0]
            self.assertEqual(bar["model"], "ModelA")
            self.assertEqual(bar["package"], "BigPkg")
            self.assertEqual(bar["source"], "standard")

    def test_index_packages_local_excludes_packages_by_pattern(self) -> None:
        from d365fo_agent.index_store import D365Index

        # A publishable standard index must be able to leave out custom/ISV packages.
        pkg_root = self.root / "PackagesLocalDirectory"
        std = pkg_root / "ApplicationX" / "ApplicationX" / "AxClass"
        std.mkdir(parents=True)
        (std / "StdClass.xml").write_text("<AxClass><Name>StdClass</Name></AxClass>", encoding="utf-8")
        custom = pkg_root / "BABCustomPkg" / "BABCustomPkg" / "AxClass"
        custom.mkdir(parents=True)
        (custom / "BABClass.xml").write_text("<AxClass><Name>BABClass</Name></AxClass>", encoding="utf-8")
        isv = pkg_root / "CDC" / "CDC" / "AxClass"
        isv.mkdir(parents=True)
        (isv / "CdcClass.xml").write_text("<AxClass><Name>CdcClass</Name></AxClass>", encoding="utf-8")

        with D365Index(self.db_path) as index:
            index.index_packages_local(pkg_root, exclude_packages=["BAB*", "CDC"])
            self.assertTrue(index.exists("StdClass", "AxClass"))
            self.assertFalse(index.exists("BABClass"))
            self.assertFalse(index.exists("CdcClass"))


class KnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo_root = create_fixture_repo(self.root)
        self.rules_path = self.root / "rules.json"
        self.rules_path.write_text(json.dumps(RULES_JSON), encoding="utf-8")
        self.db_path = self.root / "i.db"
        from d365fo_agent.index_store import D365Index
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.rules import load_rules

        self.index = D365Index(self.db_path)
        self.index.build_from_catalog(build_catalog(self.repo_root, load_rules(self.rules_path)))
        self.roots = [self.repo_root]

    def tearDown(self) -> None:
        self.index.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_get_signature_reads_methods_and_extends(self) -> None:
        from d365fo_agent import knowledge as K

        sig = K.get_signature(self.index, "BABAssetTable_Extension", self.roots)
        self.assertTrue(sig["found"])
        self.assertTrue(sig["source_available"])
        self.assertEqual(sig["extends"], "AssetTable")
        self.assertTrue(any(m["name"] == "delete" for m in sig["methods"]))

    def test_get_signature_missing_element(self) -> None:
        from d365fo_agent import knowledge as K

        sig = K.get_signature(self.index, "DoesNotExist", self.roots)
        self.assertFalse(sig["found"])

    def test_get_signature_table_extension_fields(self) -> None:
        from d365fo_agent import knowledge as K

        sig = K.get_signature(self.index, "AssetTable.BABAccountsPayable", self.roots)
        self.assertTrue(sig["found"])
        self.assertTrue(any(f["name"] == "BABLedgerJournalTransRecId" for f in sig["fields"]))

    def test_extension_chain(self) -> None:
        from d365fo_agent import knowledge as K

        chain = K.get_extension_chain(self.index, "AssetTable.BABAccountsPayable")
        self.assertIn("AssetTable", chain["extends"])

    def test_security_links(self) -> None:
        from d365fo_agent import knowledge as K

        links = K.get_security_links(self.index, "BABBFCAccount")
        self.assertTrue(any("BABBFCAccount" in s for s in links["secures"]))

    def test_entity_exposure(self) -> None:
        from d365fo_agent import knowledge as K

        exposure = K.get_entity_exposure(self.index, "BABDetailledVendInvoiceDataAreaEntity")
        self.assertTrue(exposure["found"])
        self.assertTrue(exposure["is_public"])
        self.assertTrue(exposure["data_management_enabled"])

    def test_find_similar_examples_with_content(self) -> None:
        from d365fo_agent import knowledge as K

        result = K.find_similar_examples(self.index, "BABBFCAccount", self.roots, include_content=True, limit=3)
        self.assertGreaterEqual(result["count"], 1)
        self.assertTrue(any(e.get("content") for e in result["examples"]))

    def test_sample_by_type_and_list_types(self) -> None:
        sample = self.index.sample_by_type("AxClass")
        self.assertTrue(any(s["name"] == "BABAssetTable_Extension" for s in sample))
        types = {t["artifact_type"] for t in self.index.list_types()}
        self.assertIn("AxClass", types)
        self.assertIn("AxDataEntityView", types)

    def test_scaffold_object_clones_and_renames(self) -> None:
        from d365fo_agent import knowledge as K

        result = K.scaffold_object(self.index, "AxClass", self.roots, new_name="BABNewClass")
        self.assertTrue(result["found"])
        self.assertEqual(result["based_on"], "BABAssetTable_Extension")
        self.assertIn("<Name>BABNewClass</Name>", result["xml"])
        self.assertNotIn("<Name>BABAssetTable_Extension</Name>", result["xml"])
        self.assertTrue(result["changes"])

    def test_scaffold_object_unknown_type(self) -> None:
        from d365fo_agent import knowledge as K

        result = K.scaffold_object(self.index, "AxNonexistentType", self.roots)
        self.assertFalse(result["found"])
        self.assertIn("hint", result)

    def test_scaffold_object_sets_properties(self) -> None:
        from d365fo_agent import knowledge as K

        result = K.scaffold_object(self.index, "AxClass", self.roots, new_name="BABNewClass",
                                   properties={"Label": "@BAB:Foo"})
        self.assertTrue(result["found"])
        self.assertIn("<Label>@BAB:Foo</Label>", result["xml"])  # inserted (AxClass has no top-level Label)
        self.assertTrue(any("Label" in c for c in result["changes"]))


class ValidateTests(unittest.TestCase):
    def test_valid_service(self) -> None:
        from d365fo_agent.validate import validate_xml

        xml = "<AxService><Name>S</Name><Class>C</Class><Operations><AxServiceOperation><Name>o</Name></AxServiceOperation></Operations></AxService>"
        report = validate_xml(xml, "service")
        self.assertTrue(report["valid"])
        self.assertEqual(report["errors"], [])

    def test_malformed_xml(self) -> None:
        from d365fo_agent.validate import validate_xml

        report = validate_xml("<AxClass><Name>x</Foo>", "class-extension")
        self.assertFalse(report["valid"])
        self.assertTrue(any("well-formed" in e for e in report["errors"]))

    def test_wrong_root_for_family(self) -> None:
        from d365fo_agent.validate import validate_xml

        report = validate_xml("<AxClass><Name>x</Name><SourceCode/></AxClass>", "service")
        self.assertFalse(report["valid"])
        self.assertTrue(any("does not match family" in e for e in report["errors"]))

    def test_missing_name(self) -> None:
        from d365fo_agent.validate import validate_xml

        report = validate_xml("<AxService><Class>C</Class><Operations/></AxService>", "service")
        self.assertFalse(report["valid"])

    def test_empty_container_warning(self) -> None:
        from d365fo_agent.validate import validate_xml

        report = validate_xml("<AxService><Name>S</Name><Class>C</Class><Operations/></AxService>", "service")
        self.assertTrue(report["valid"])
        self.assertTrue(any("empty" in w.lower() for w in report["warnings"]))

    def test_learned_profile_validates_unknown_root(self) -> None:
        from d365fo_agent.validate import validate_xml

        profiles = {"AxKpiThing": {"required": ["Name", "Calculation"], "recommended": ["Label"]}}
        bad = validate_xml("<AxKpiThing><Name>X</Name></AxKpiThing>", type_profiles=profiles)
        self.assertEqual(bad["rule_source"], "learned")
        self.assertFalse(bad["valid"])
        self.assertTrue(any("Calculation" in e for e in bad["errors"]))
        good = validate_xml("<AxKpiThing><Name>X</Name><Calculation>c</Calculation></AxKpiThing>", type_profiles=profiles)
        self.assertTrue(good["valid"])
        self.assertEqual(good["rule_source"], "learned")

    def test_curated_rules_win_over_profile(self) -> None:
        from d365fo_agent.validate import validate_xml

        profiles = {"AxService": {"required": ["NeverPresent"], "recommended": []}}
        xml = "<AxService><Name>S</Name><Class>C</Class><Operations><AxServiceOperation><Name>o</Name></AxServiceOperation></Operations></AxService>"
        report = validate_xml(xml, "service", type_profiles=profiles)
        self.assertEqual(report["rule_source"], "curated")
        self.assertTrue(report["valid"])

    def test_generic_fallback_for_unknown_root_without_profile(self) -> None:
        from d365fo_agent.validate import validate_xml

        report = validate_xml("<AxWeirdType><Name>X</Name></AxWeirdType>")
        self.assertEqual(report["rule_source"], "generic")
        self.assertTrue(report["valid"])


class TypeProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo_root = create_fixture_repo(self.root)
        self.rules_path = self.root / "rules.json"
        self.rules_path.write_text(json.dumps(RULES_JSON), encoding="utf-8")
        from d365fo_agent.index_store import D365Index
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.rules import load_rules

        self.index = D365Index(self.root / "i.db")
        self.index.build_from_catalog(build_catalog(self.repo_root, load_rules(self.rules_path)))

    def tearDown(self) -> None:
        self.index.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_build_profiles_from_corpus(self) -> None:
        from d365fo_agent.type_profile import build_type_profiles

        profiles = build_type_profiles(self.index, [self.repo_root])
        self.assertIn("AxClass", profiles)
        self.assertIn("SourceCode", profiles["AxClass"]["known"])
        self.assertEqual(profiles["AxClass"]["sample_size"], 1)
        # a data entity's public-exposure children are learned as present
        self.assertIn("PublicEntityName", profiles["AxDataEntityView"]["known"])

    def test_save_and_load_roundtrip(self) -> None:
        from d365fo_agent.type_profile import build_type_profiles, load_type_profiles, save_type_profiles

        profiles = build_type_profiles(self.index, [self.repo_root])
        path = self.root / "profiles.json"
        save_type_profiles(profiles, path)
        loaded = load_type_profiles(path)
        self.assertEqual(set(loaded), set(profiles))
        self.assertIsNone(load_type_profiles(self.root / "missing.json"))


class LinterEdtTypeTests(unittest.TestCase):
    """field-type-matches-edt must catch a wrong AOT field type on a STANDARD-style EDT (stored as a
    generic 'AxEdt' folder with the subtype only in i:type) — which needs file roots to read."""

    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.pkg_root = self.root / "PLD"
        edt_dir = self.pkg_root / "EdtPkg" / "EdtPkg" / "AxEdt"
        edt_dir.mkdir(parents=True)
        (edt_dir / "MyAmount.xml").write_text(
            '<AxEdt xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="" i:type="AxEdtReal">'
            "<Name>MyAmount</Name></AxEdt>",
            encoding="utf-8",
        )
        from d365fo_agent.index_store import D365Index

        self.index = D365Index(self.root / "i.db")
        self.index.index_packages_local(self.pkg_root)
        self.roots = [self.pkg_root]

    def tearDown(self) -> None:
        self.index.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def _field_xml(self, field_type: str) -> str:
        return (
            '<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance"><Name>SomeTable.M</Name>'
            f'<Fields><AxTableField xmlns="" i:type="{field_type}"><Name>BABAmt</Name>'
            "<ExtendedDataType>MyAmount</ExtendedDataType></AxTableField></Fields></AxTableExtension>"
        )

    def test_wrong_field_type_on_standard_edt_is_flagged(self) -> None:
        from d365fo_agent.linter import lint_artifact

        report = lint_artifact(self._field_xml("AxTableFieldString"), "table-extension",
                               index=self.index, roots=self.roots)
        self.assertTrue(any(f["rule_id"] == "field-type-matches-edt" for f in report["findings"]),
                        "expected AxEdtReal -> AxTableFieldReal mismatch to be flagged")

    def test_correct_field_type_passes(self) -> None:
        from d365fo_agent.linter import lint_artifact

        report = lint_artifact(self._field_xml("AxTableFieldReal"), "table-extension",
                               index=self.index, roots=self.roots)
        self.assertFalse(any(f["rule_id"] == "field-type-matches-edt" for f in report["findings"]))

    def test_no_roots_cannot_type_standard_edt(self) -> None:
        # Without roots the linter cannot read i:type, so it must NOT flag (no false positive).
        from d365fo_agent.linter import lint_artifact

        report = lint_artifact(self._field_xml("AxTableFieldString"), "table-extension", index=self.index)
        self.assertFalse(any(f["rule_id"] == "field-type-matches-edt" for f in report["findings"]))


class KnowledgeFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def _opener(payload: bytes):
        import io

        return lambda url: io.BytesIO(payload)

    def test_no_url_configured(self) -> None:
        from unittest import mock

        from d365fo_agent import knowledge_fetch
        from d365fo_agent.knowledge_fetch import fetch_knowledge

        with mock.patch.object(knowledge_fetch, "DEFAULT_KNOWLEDGE_URL", ""):
            result = fetch_knowledge(url=None, dest=self.root / "k.db")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_plain_download(self) -> None:
        from d365fo_agent.knowledge_fetch import fetch_knowledge

        dest = self.root / "k.db"
        result = fetch_knowledge(url="https://example.test/k.db", dest=dest, opener=self._opener(b"SQLITE-DATA"))
        self.assertTrue(result["ok"])
        self.assertEqual(dest.read_bytes(), b"SQLITE-DATA")

    def test_gzip_download_is_decompressed(self) -> None:
        import gzip

        from d365fo_agent.knowledge_fetch import fetch_knowledge

        dest = self.root / "k.db"
        result = fetch_knowledge(url="https://example.test/k.db.gz", dest=dest,
                                 opener=self._opener(gzip.compress(b"PLAIN-DB")))
        self.assertTrue(result["ok"])
        self.assertEqual(dest.read_bytes(), b"PLAIN-DB")

    def test_skip_when_present(self) -> None:
        from d365fo_agent.knowledge_fetch import fetch_knowledge

        dest = self.root / "k.db"
        dest.write_bytes(b"existing")
        result = fetch_knowledge(url="https://example.test/k.db", dest=dest, opener=self._opener(b"new"))
        self.assertTrue(result.get("skipped"))
        self.assertEqual(dest.read_bytes(), b"existing")

    def test_non_http_rejected(self) -> None:
        from d365fo_agent.knowledge_fetch import fetch_knowledge

        result = fetch_knowledge(url="file:///etc/passwd", dest=self.root / "k.db")
        self.assertFalse(result["ok"])


class McpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo_root = create_fixture_repo(self.root)
        self.rules_path = self.root / "rules.json"
        self.rules_path.write_text(json.dumps(RULES_JSON), encoding="utf-8")
        self.db_path = self.root / "i.db"
        methodology = self.root / "method.md"
        methodology.write_text("# Methodology\nExtension first.", encoding="utf-8")
        from d365fo_agent.index_store import D365Index
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.mcp_server import D365MCPServer
        from d365fo_agent.rules import load_rules

        with D365Index(self.db_path) as index:
            index.build_from_catalog(build_catalog(self.repo_root, load_rules(self.rules_path)))
        self.server = D365MCPServer(self.repo_root, self.rules_path, self.db_path, None, methodology)

    def tearDown(self) -> None:
        if self.server._index is not None:
            self.server._index.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def _rpc(self, method, params=None, mid=1):
        return self.server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})

    def _tool(self, name, args):
        resp = self._rpc("tools/call", {"name": name, "arguments": args})
        self.assertIn("result", resp)
        payload = json.loads(resp["result"]["content"][0]["text"])
        return resp["result"].get("isError"), payload

    def test_initialize(self) -> None:
        resp = self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        self.assertEqual(resp["result"]["serverInfo"]["name"], "d365fo-agent")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_tools_list_nonempty(self) -> None:
        resp = self._rpc("tools/list")
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("element_exists", names)
        self.assertIn("get_signature", names)
        self.assertIn("validate_xml", names)

    def test_notification_gets_no_response(self) -> None:
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unknown_method_errors(self) -> None:
        resp = self._rpc("does/notexist")
        self.assertEqual(resp["error"]["code"], -32601)

    def test_element_exists_tool(self) -> None:
        err, payload = self._tool("element_exists", {"name": "BABBFCAccount"})
        self.assertFalse(err)
        self.assertTrue(payload["exists"])
        err, payload = self._tool("element_exists", {"name": "GhostElement"})
        self.assertFalse(payload["exists"])

    def test_validate_xml_tool(self) -> None:
        err, payload = self._tool(
            "validate_xml",
            {"xml": "<AxService><Name>S</Name><Class>C</Class><Operations/></AxService>", "family": "service"},
        )
        self.assertFalse(err)
        self.assertTrue(payload["valid"])

    def test_get_methodology_tool(self) -> None:
        err, payload = self._tool("get_methodology", {})
        self.assertFalse(err)
        self.assertIn("Extension first", payload["methodology"])

    def test_knowledge_only_mode_no_repo(self) -> None:
        # Server runs from the index alone (no repo/rules): discovery + bundled methodology/profiles.
        from d365fo_agent.mcp_server import build_server_from_config

        srv = build_server_from_config(db_path=self.db_path)
        try:
            self.assertIsNone(srv.rules_path)
            self.assertTrue(srv.type_profiles)  # falls back to the bundled default profile
            exists = json.loads(srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "element_exists", "arguments": {"name": "BABBFCAccount"}}})["result"]["content"][0]["text"])
            self.assertTrue(exists["exists"])
            method = json.loads(srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "get_methodology", "arguments": {}}})["result"]["content"][0]["text"])
            self.assertIsNotNone(method["methodology"])
        finally:
            if srv._index is not None:
                srv._index.close()

    def test_unknown_tool_is_error(self) -> None:
        resp = self._rpc("tools/call", {"name": "no_such_tool", "arguments": {}})
        self.assertIn("error", resp)

    def test_resources(self) -> None:
        resp = self._rpc("resources/list")
        uris = {r["uri"] for r in resp["result"]["resources"]}
        self.assertIn("d365fo://methodology", uris)
        read = self._rpc("resources/read", {"uri": "d365fo://methodology"})
        self.assertIn("Extension first", read["result"]["contents"][0]["text"])

    def test_derive_entity_tool(self) -> None:
        err, payload = self._tool("derive_entity", {
            "source_entity": "BABDetailledVendInvoiceDataAreaEntity",
            "new_name": "BABExportInvoiceEntity",
            "public_entity_name": "BABExportInvoice",
        })
        self.assertFalse(err)
        self.assertTrue(payload["found"] and payload["source_available"])
        self.assertEqual(payload["entity"]["name"], "BABExportInvoiceEntity")
        self.assertIn("<IsPublic>Yes</IsPublic>", payload["entity"]["xml"])
        self.assertIn("<AxSecurityDataEntityPermission>", payload["privilege"]["xml"])
        self.assertTrue(payload["privilege"]["validate"]["valid"])

    def test_derive_entity_unknown_source(self) -> None:
        err, payload = self._tool("derive_entity", {"source_entity": "GhostEntity", "new_name": "BABx"})
        self.assertFalse(payload["found"])

    def test_wire_security_create_mode(self) -> None:
        # extend_*=false -> create new custom duty + role (no standard target needed in the fixture).
        err, payload = self._tool("wire_security", {
            "privilege": "BABBFCAccountEntityMaintain", "duty": "BABBFCMaintain", "role": "BABBFCRole",
            "extend_duty": False, "extend_role": False,
        })
        self.assertFalse(err)
        self.assertTrue(payload["wired"])
        families = [a["family"] for a in payload["artifacts"]]
        self.assertEqual(families, ["security-duty", "security-role"])
        self.assertTrue(all(a["validate"]["valid"] for a in payload["artifacts"]))
        self.assertIn("BABBFCAccountEntityMaintain", payload["chain"])

    def test_scaffold_object_tool(self) -> None:
        err, payload = self._tool("scaffold_object", {"artifact_type": "AxClass", "new_name": "BABNewClass"})
        self.assertFalse(err)
        self.assertTrue(payload["found"])
        self.assertIn("<Name>BABNewClass</Name>", payload["xml"])

    def test_index_stats_lists_supported_types(self) -> None:
        err, payload = self._tool("index_stats", {})
        self.assertFalse(err)
        types = {t["artifact_type"] for t in payload["supported_object_types"]}
        self.assertIn("AxClass", types)

    def test_wire_security_warns_on_unverified_extension_target(self) -> None:
        # Extending a duty not indexed as AxSecurityDuty still produces the artifact but warns.
        err, payload = self._tool("wire_security", {
            "privilege": "BABBFCAccountEntityMaintain", "duty": "GhostStandardDuty", "suffix": "BABBFC",
        })
        self.assertFalse(err)
        self.assertTrue(payload["wired"])
        self.assertTrue(any(not c["in_index"] for c in payload["target_checks"]))
        self.assertTrue(any("GhostStandardDuty" in w for w in payload["warnings"]))


if __name__ == "__main__":
    unittest.main()
