"""Tests for the X++ coding-rule linter."""

import shutil
import unittest
from uuid import uuid4

from test_catalog import TEST_TEMP_ROOT


def _ids(report):
    return [f["rule_id"] for f in report["findings"]]


class LinterNoIndexTests(unittest.TestCase):
    """Rules that do not need the index (naming, labels, field-type heuristic, privilege, entity)."""

    def lint(self, xml, family=None, model=None):
        from d365fo_agent.linter import lint_artifact

        return lint_artifact(xml, family, model=model)

    def test_naming_prefix_flags_unprefixed_object(self):
        report = self.lint("<AxClass><Name>SomeHelper</Name><SourceCode/></AxClass>", "class-extension")
        self.assertIn("naming-prefix", _ids(report))

    def test_naming_prefix_accepts_prefixed_object(self):
        report = self.lint("<AxClass><Name>BABSomeHelper</Name><SourceCode/></AxClass>", "class-extension")
        self.assertNotIn("naming-prefix", _ids(report))

    def test_naming_prefix_checks_extension_model_segment(self):
        report = self.lint("<AxTableExtension><Name>CustTable.SomeModel</Name><Fields/></AxTableExtension>", "table-extension")
        self.assertIn("naming-prefix", _ids(report))
        report_ok = self.lint("<AxTableExtension><Name>CustTable.BABAccountsPayable</Name><Fields/></AxTableExtension>", "table-extension")
        self.assertNotIn("naming-prefix", _ids(report_ok))

    def test_label_not_literal(self):
        report = self.lint("<AxMenuItemDisplay><Name>BABx</Name><Label>Hard coded</Label><Object>F</Object></AxMenuItemDisplay>")
        self.assertIn("label-not-literal", _ids(report))

    def test_label_reference_accepted(self):
        report = self.lint("<AxMenuItemDisplay><Name>BABx</Name><Label>@BABFile:Id</Label><Object>F</Object></AxMenuItemDisplay>")
        self.assertNotIn("label-not-literal", _ids(report))

    def test_field_type_mismatch_is_error_heuristic(self):
        xml = ('<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
               '<Name>CustTable.BABAccountsPayable</Name><Fields>'
               '<AxTableField xmlns="" i:type="AxTableFieldString"><Name>BABr</Name><ExtendedDataType>RefRecId</ExtendedDataType></AxTableField>'
               '</Fields></AxTableExtension>')
        report = self.lint(xml, "table-extension")
        self.assertIn("field-type-matches-edt", _ids(report))
        self.assertEqual(report["error_count"], 1)

    def test_field_type_correct_passes(self):
        xml = ('<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
               '<Name>CustTable.BABAccountsPayable</Name><Fields>'
               '<AxTableField xmlns="" i:type="AxTableFieldInt64"><Name>BABr</Name><ExtendedDataType>RefRecId</ExtendedDataType></AxTableField>'
               '</Fields></AxTableExtension>')
        report = self.lint(xml, "table-extension")
        self.assertNotIn("field-type-matches-edt", _ids(report))

    def test_privilege_read_only_is_info(self):
        xml = ('<AxSecurityPrivilege><Name>BABPriv</Name><EntryPoints>'
               '<AxSecurityEntryPointReference><Name>x</Name><Grant><Read>Allow</Read></Grant>'
               '<ObjectName>x</ObjectName><ObjectType>MenuItemDisplay</ObjectType></AxSecurityEntryPointReference>'
               '</EntryPoints></AxSecurityPrivilege>')
        report = self.lint(xml, "security-privilege")
        self.assertIn("privilege-grant-explicit", _ids(report))

    def test_data_entity_completeness(self):
        xml = "<AxDataEntityView><Name>BABEntity</Name><Fields/><Keys/></AxDataEntityView>"
        report = self.lint(xml, "data-entity")
        self.assertIn("data-entity-completeness", _ids(report))

    def test_index_rules_skipped_without_index(self):
        report = self.lint("<AxTableExtension><Name>CustTable.BABAccountsPayable</Name><Fields/></AxTableExtension>", "table-extension")
        skipped = [s["rule"] for s in report["rules_skipped"] if "index" in s["reason"]]
        self.assertIn("extension-target-exists", skipped)
        self.assertIn("no-legacy-reference", skipped)

    def test_malformed_xml_is_error(self):
        report = self.lint("<AxClass><Name>x</Foo>")
        self.assertEqual(report["error_count"], 1)

    def test_config_can_disable_a_rule(self):
        from d365fo_agent.linter import LintConfig, lint_artifact

        cfg = LintConfig(rules={"naming-prefix": {"enabled": False, "severity": "warning"}})
        report = lint_artifact("<AxClass><Name>Unprefixed</Name><SourceCode/></AxClass>", "class-extension", config=cfg)
        self.assertNotIn("naming-prefix", _ids(report))


class LinterIndexBackedTests(unittest.TestCase):
    def setUp(self):
        from d365fo_agent.index_store import D365Index
        from d365fo_agent.models import Artifact, Catalog

        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        catalog = Catalog(
            models=["BABAccountsPayable"],
            artifacts=[
                Artifact("RealTable", "AxTable", "BABAccountsPayable", "BABAccountsPayable", "custom-canonical", "p/RealTable.xml"),
                Artifact("BABMyEnum", "AxEnum", "BABAccountsPayable", "BABAccountsPayable", "custom-canonical", "p/BABMyEnum.xml"),
                Artifact("OldTable", "AxTable", "LegacyModel", "LegacyModel", "legacy-deprecated", "legacy/OldTable.xml"),
            ],
            relations=[],
        )
        self.index = D365Index(self.root / "i.db")
        self.index.build_from_catalog(catalog)

    def tearDown(self):
        self.index.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def lint(self, xml, family=None):
        from d365fo_agent.linter import lint_artifact

        return lint_artifact(xml, family, index=self.index)

    def test_extension_target_exists_passes_for_real_target(self):
        report = self.lint("<AxTableExtension><Name>RealTable.BABAccountsPayable</Name><Fields/></AxTableExtension>", "table-extension")
        self.assertNotIn("extension-target-exists", _ids(report))

    def test_extension_target_missing_is_error(self):
        report = self.lint("<AxTableExtension><Name>GhostTable.BABAccountsPayable</Name><Fields/></AxTableExtension>", "table-extension")
        self.assertIn("extension-target-exists", _ids(report))
        self.assertEqual(report["error_count"], 1)

    def test_no_legacy_reference_flags_deprecated_target(self):
        report = self.lint("<AxTableExtension><Name>OldTable.BABAccountsPayable</Name><Fields/></AxTableExtension>", "table-extension")
        self.assertIn("no-legacy-reference", _ids(report))

    def test_field_type_resolved_via_index_enum(self):
        # BABMyEnum is an AxEnum in the index -> a field of that EDT must be AxTableFieldEnum.
        xml = ('<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
               '<Name>RealTable.BABAccountsPayable</Name><Fields>'
               '<AxTableField xmlns="" i:type="AxTableFieldString"><Name>BABe</Name><ExtendedDataType>BABMyEnum</ExtendedDataType></AxTableField>'
               '</Fields></AxTableExtension>')
        report = self.lint(xml, "table-extension")
        self.assertIn("field-type-matches-edt", _ids(report))


if __name__ == "__main__":
    unittest.main()
