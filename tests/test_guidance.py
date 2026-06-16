import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from test_catalog import TEST_TEMP_ROOT

COC_TOPIC = """---
id: coc-extension
title: Chain of Command (méthode)
summary: Étendre une méthode standard sans overlayering, via une classe d'extension.
platform: d365fo
object_types: AxClass
grounds: CustTable, SysExtension
example_type: AxClass
example_query: ExtensionOf
related_topics: table-extension-fields
related_tools: get_signature, compile_generated
---
## Syntaxe
`[ExtensionOf(tableStr(CustTable))] final class Foo_Extension` ; appeler `next maMethode();`.

## Règles
La classe doit être `final` ; le préfixe modèle est obligatoire ; un `next` est requis pour
les méthodes wrappées non-void.

## Logique
Préférer CoC quand on doit modifier le comportement d'une méthode existante ; préférer un
event handler quand un point d'extension délégué existe déjà.
"""

AX2012_TOPIC = """---
id: ax2012-overlayer
title: Personnalisation par overlayering (AX 2012)
summary: Modèle d'extension legacy AX 2012, sans Chain of Command.
platform: ax2012
object_types: AxClass
grounds: SysOperationServiceController
related_tools: get_signature
---
## Syntaxe
Surcharge directe dans une couche supérieure (VAR/CUS/USR).

## Règles
Pas de Chain of Command en AX 2012 ; l'overlayering modifie l'objet en place.

## Logique
Choisir la couche la plus haute appropriée ; éviter de modifier la couche SYS.
"""


class _FakeIndex:
    """Duck-typed stand-in for D365Index — only what guidance needs."""

    def __init__(self, present: set[str]) -> None:
        self._present = present

    def exists(self, name: str, artifact_type: str | None = None) -> bool:
        return name in self._present

    def search(self, query: str, *, artifact_type: str | None = None, limit: int = 20):
        return [{"name": "CustTable_CoCSample", "artifact_type": "AxClass",
                 "model": "AppSuite", "relative_path": "x/AxClass/CustTable_CoCSample.xml"}]


class GuidanceTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.dir = self.root / "guidance"
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "coc-extension.md").write_text(COC_TOPIC, encoding="utf-8")
        (self.dir / "ax2012-overlayer.md").write_text(AX2012_TOPIC, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_load_parses_frontmatter_and_sections(self) -> None:
        from d365fo_agent.guidance import load_guidance

        topics = load_guidance(self.dir)
        self.assertEqual(set(topics), {"coc-extension", "ax2012-overlayer"})
        coc = topics["coc-extension"]
        self.assertEqual(coc.platform, "d365fo")
        self.assertEqual(coc.object_types, ["AxClass"])
        self.assertEqual(coc.grounds, ["CustTable", "SysExtension"])
        self.assertEqual(coc.related_tools, ["get_signature", "compile_generated"])
        self.assertIn("ExtensionOf", coc.sections["syntaxe"])
        self.assertIn("final", coc.sections["règles"])

    def test_list_filters_by_platform_and_type(self) -> None:
        from d365fo_agent.guidance import list_guidance, load_guidance

        topics = load_guidance(self.dir)
        ids = {t["id"] for t in list_guidance(topics, platform="d365fo")}
        self.assertEqual(ids, {"coc-extension"})
        ids = {t["id"] for t in list_guidance(topics, object_type="AxClass")}
        self.assertEqual(ids, {"coc-extension", "ax2012-overlayer"})

    def test_get_annotates_grounding_and_pulls_example(self) -> None:
        from d365fo_agent.guidance import get_guidance, load_guidance

        topics = load_guidance(self.dir)
        index = _FakeIndex(present={"CustTable"})  # SysExtension absent -> flagged
        out = get_guidance(topics, "coc-extension", index=index, roots=[Path(".")])
        grounding = {g["name"]: g["in_index"] for g in out["grounding"]}
        self.assertEqual(grounding, {"CustTable": True, "SysExtension": False})
        self.assertTrue(out["example"]["found"])
        self.assertEqual(out["example"]["name"], "CustTable_CoCSample")
        self.assertIn("syntaxe", out["sections"])

    def test_get_without_index_still_returns_prose(self) -> None:
        from d365fo_agent.guidance import get_guidance, load_guidance

        topics = load_guidance(self.dir)
        out = get_guidance(topics, "coc-extension")
        self.assertIn("règles", out["sections"])
        self.assertIsNone(out["example"])
        # grounding listed but not verified
        self.assertTrue(all(g["in_index"] is None for g in out["grounding"]))

    def test_search_matches_task_phrasing(self) -> None:
        from d365fo_agent.guidance import load_guidance, search_guidance

        topics = load_guidance(self.dir)
        hits = search_guidance(topics, "chain of command extension method", platform="d365fo")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "coc-extension")

    def test_grounding_report_flags_missing(self) -> None:
        from d365fo_agent.guidance import grounding_report, load_guidance

        topics = load_guidance(self.dir)
        index = _FakeIndex(present={"CustTable", "SysExtension", "SysOperationServiceController"})
        report = grounding_report(topics, index)
        self.assertEqual(report, {})  # all grounded -> no missing
        index2 = _FakeIndex(present={"CustTable"})
        report2 = grounding_report(topics, index2)
        self.assertIn("SysExtension", report2.get("coc-extension", []))

    def test_unknown_topic_suggests(self) -> None:
        from d365fo_agent.guidance import get_guidance, load_guidance

        topics = load_guidance(self.dir)
        out = get_guidance(topics, "coc")
        self.assertFalse(out["found"])
        self.assertIn("coc-extension", out["suggestions"])

    def test_bundled_guidance_dir_exists_and_grounds(self) -> None:
        # The shipped guidance must load and declare valid platforms.
        from d365fo_agent.guidance import default_guidance_dir, list_guidance, load_guidance

        d = default_guidance_dir()
        self.assertIsNotNone(d, "bundled data/guidance directory must exist")
        topics = load_guidance(d)
        self.assertGreaterEqual(len(topics), 4)
        for t in list_guidance(topics):
            self.assertIn(t["platform"], {"d365fo", "ax2012", "both"})

    def test_bundled_topics_are_grounded_against_real_index(self) -> None:
        # Anti-hallucination on real data: every element a shipped D365 F&O topic references must
        # exist in the canonical index (or be a known kernel type). Skip-guarded — needs the index.
        canonical = Path(__file__).resolve().parents[1] / ".omx" / "index" / "d365fo.db"
        if not canonical.exists():
            self.skipTest("canonical index .omx/index/d365fo.db not present")
        from d365fo_agent.guidance import default_guidance_dir, grounding_report, load_guidance
        from d365fo_agent.index_store import D365Index

        topics = {tid: t for tid, t in load_guidance(default_guidance_dir()).items()
                  if t.platform in ("d365fo", "both")}
        index = D365Index(canonical)
        try:
            report = grounding_report(topics, index)
        finally:
            index.close()
        self.assertEqual(report, {}, f"ungrounded references in shipped guidance: {report}")


class GuidanceMcpToolTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _call(self, srv, name, args):
        import json

        resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": args}})
        return json.loads(resp["result"]["content"][0]["text"])

    def test_tools_registered_and_degrade_without_index(self) -> None:
        from d365fo_agent.mcp_server import build_server_from_config

        # Point at a non-existent DB: guidance prose must still work; example just unavailable.
        srv = build_server_from_config(db_path=self.root / "missing.db")
        try:
            for tool in ("list_guidance", "get_guidance", "search_guidance"):
                self.assertIn(tool, srv.tools)
            listed = self._call(srv, "list_guidance", {"platform": "d365fo"})
            ids = {t["id"] for t in listed["topics"]}
            self.assertIn("coc-extension", ids)

            got = self._call(srv, "get_guidance", {"topic": "coc-extension"})
            self.assertTrue(got["found"])
            self.assertIn("syntax", got["sections"])
            self.assertIsNone(got["example"])  # no index ready -> no example, but prose present

            hits = self._call(srv, "search_guidance", {"query": "extend a standard method"})
            self.assertTrue(hits["results"])
        finally:
            if srv._index is not None:
                srv._index.close()


if __name__ == "__main__":
    unittest.main()
