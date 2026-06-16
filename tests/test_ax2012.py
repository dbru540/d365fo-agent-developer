import os
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from test_catalog import TEST_TEMP_ROOT

# A multi-element .xpo (a SharedProject bundles several AOT objects, each its own ***Element).
XPO = """﻿Exportfile for AOT version 1.0 or later
Formatversion: 1

***Element: CLS

; Microsoft Dynamics AX Class : ContosoHelper
  CLSVERSION 1
  CLASS #ContosoHelper
    PROPERTIES
      Name                #ContosoHelper
      Extends             #DMFEntityBase
    ENDPROPERTIES
    METHODS
      SOURCE #run
        #public void run() {}
    ENDMETHODS
  ENDCLASS

***Element: TAB
  TABLE #ContosoTable
    PROPERTIES
      Name                #ContosoTable
    ENDPROPERTIES

***Element: SRO
  ROLE #ContosoSecRole
      Name                #ContosoSecRole
    DUTIES #Duties
      DUTY #BOMBillsOfMaterialsApprove
"""


class Ax2012ParserTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.xpo = self.root / "SharedProject_Demo.xpo"
        self.xpo.write_text(XPO, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_parse_extracts_exported_elements_not_references(self) -> None:
        from d365fo_agent.ax2012_indexer import parse_xpo

        elements = parse_xpo(self.xpo)
        got = {(e["name"], e["artifact_type"]) for e in elements}
        self.assertEqual(got, {
            ("ContosoHelper", "AxClass"),
            ("ContosoTable", "AxTable"),
            ("ContosoSecRole", "AxSecurityRole"),
        })
        # The nested DUTY reference inside the role is NOT an exported element -> not cataloged.
        self.assertNotIn(("BOMBillsOfMaterialsApprove", "AxSecurityDuty"), got)
        # Extends captured for the class.
        cls = next(e for e in elements if e["name"] == "ContosoHelper")
        self.assertEqual(cls.get("extends"), "DMFEntityBase")

    def test_build_catalog_and_index(self) -> None:
        from d365fo_agent.ax2012_indexer import build_ax2012_catalog
        from d365fo_agent.index_store import D365Index

        catalog = build_ax2012_catalog([self.root])
        names = {a.name for a in catalog.artifacts}
        self.assertEqual(names, {"ContosoHelper", "ContosoTable", "ContosoSecRole"})
        self.assertTrue(all(a.classification == "ax2012-custom" for a in catalog.artifacts))

        db = self.root / "ax2012.db"
        with D365Index(db) as index:
            index.build_from_catalog(catalog, source="ax2012")
            self.assertTrue(index.exists("ContosoHelper", "AxClass"))
            self.assertTrue(index.exists("ContosoTable", "AxTable"))
            self.assertFalse(index.exists("BOMBillsOfMaterialsApprove"))

    def test_real_corpus_smoke(self) -> None:
        # Skip-guarded: index a real .xpo corpus if D365FO_AX_CORPUS points at one (no hardcoded
        # client path in the committed test).
        env = os.environ.get("D365FO_AX_CORPUS")
        if not env:
            self.skipTest("set D365FO_AX_CORPUS to a folder of .xpo files to run this")
        corpus = Path(env)
        from d365fo_agent.ax2012_indexer import _iter_xpo, build_ax2012_catalog

        if not corpus.exists() or not _iter_xpo(corpus):
            self.skipTest("D365FO_AX_CORPUS has no .xpo files")
        catalog = build_ax2012_catalog([corpus])
        self.assertGreater(len(catalog.artifacts), 50)
        types = {a.artifact_type for a in catalog.artifacts}
        self.assertTrue(types & {"AxClass", "AxTable", "AxSecurityRole"})


if __name__ == "__main__":
    unittest.main()
