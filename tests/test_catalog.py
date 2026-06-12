import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from uuid import uuid4


MODEL_DESCRIPTOR = """<?xml version="1.0" encoding="utf-8"?>
<AxModelInfo xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Description>Accounts payable package</Description>
  <DisplayName>BABAccountsPayable</DisplayName>
  <Layer>10</Layer>
  <ModuleReferences xmlns:d2p1="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
    <d2p1:string>ApplicationFoundation</d2p1:string>
    <d2p1:string>ApplicationSuite</d2p1:string>
  </ModuleReferences>
  <Name>BABAccountsPayable</Name>
  <Publisher>Flexmind</Publisher>
</AxModelInfo>
"""


CLASS_XML = """<?xml version="1.0" encoding="utf-8"?>
<AxClass xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>BABAssetTable_Extension</Name>
  <SourceCode>
    <Declaration><![CDATA[
[ExtensionOf(tableStr(AssetTable))]
final class BABAssetTable_Extension
{
}
]]></Declaration>
    <Methods>
      <Method>
        <Name>delete</Name>
        <Source><![CDATA[
    public void delete()
    {
        next delete();
    }
]]></Source>
      </Method>
    </Methods>
  </SourceCode>
</AxClass>
"""


TABLE_EXTENSION_XML = """<?xml version="1.0" encoding="utf-8"?>
<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>AssetTable.BABAccountsPayable</Name>
  <Fields>
    <AxTableField xmlns="" i:type="AxTableFieldInt64">
      <Name>BABLedgerJournalTransRecId</Name>
      <ExtendedDataType>RefRecId</ExtendedDataType>
    </AxTableField>
  </Fields>
  <Relations>
    <AxTableRelation>
      <Name>BABLedgerJournalTrans</Name>
      <RelatedTable>LedgerJournalTrans</RelatedTable>
    </AxTableRelation>
  </Relations>
</AxTableExtension>
"""


DATA_ENTITY_XML = """<?xml version="1.0" encoding="utf-8"?>
<AxDataEntityView xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>BABDetailledVendInvoiceDataAreaEntity</Name>
  <Label>@BABVendorsInterface:VendDetailledInvoicesParamEntityHeader</Label>
  <DataManagementEnabled>Yes</DataManagementEnabled>
  <IsPublic>Yes</IsPublic>
  <PublicCollectionName>DetailledVendInvoiceDataAreas</PublicCollectionName>
  <PublicEntityName>DetailledVendInvoiceDataArea</PublicEntityName>
</AxDataEntityView>
"""


SECURITY_PRIVILEGE_XML = """<?xml version="1.0" encoding="utf-8"?>
<AxSecurityPrivilege xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>BABBFCAccount</Name>
  <Label>@BABExportBFC:BFCLedgerAccount</Label>
  <EntryPoints>
    <AxSecurityEntryPointReference>
      <Name>BABBFCAccount</Name>
      <ObjectName>BABBFCAccount</ObjectName>
      <ObjectType>MenuItemDisplay</ObjectType>
    </AxSecurityEntryPointReference>
  </EntryPoints>
</AxSecurityPrivilege>
"""


REPORT_XML = """<?xml version="1.0" encoding="utf-8"?>
<AxReport xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="Microsoft.Dynamics.AX.Metadata.V2">
  <Name>BABCheque_BOA</Name>
  <DataSets>
    <AxReportDataSet xmlns="">
      <Name>Cheque_BOADS</Name>
      <DataSourceType>ReportDataProvider</DataSourceType>
      <Query>SELECT * FROM BABChequeDP_BOA.BABChequeTmp_BOA</Query>
    </AxReportDataSet>
  </DataSets>
</AxReport>
"""


RULES_JSON = {
    "default_classification": "custom-canonical",
    "rules": [
        {"match": "model_exact", "value": "BHSLicenseBase", "classification": "isv-reference"},
        {"match": "path_contains", "value": "\\\\legacy\\\\", "classification": "legacy-deprecated"},
    ],
}


XREF_LINES = [
    "/Forms/BABCustVendAgingBucketLookUp/Methods/init|/Classes/FormRun/Methods/init|MethodCall|8|9||Xppc.exe|BABAccountsPayable|ApplicationPlatform",
    "Enum/BABVendAgingOrderBy?Label|/Labels/@SYS5777|TypeReference|0|0||Metadata|BABAccountsPayable|ApplicationPlatform",
]


# Use the (short) system temp dir, not <repo>/.test_tmp. The repo path is already ~65 chars and
# the deepest generated artifact path adds ~199 more (>260), which trips the Windows MAX_PATH
# limit on two tests. A short root keeps every generated path under 260 on Windows and is
# unaffected on Linux/WSL (PATH_MAX 4096). Override with D365FO_TEST_TMP if needed.
import os as _os  # noqa: E402

TEST_TEMP_ROOT = Path(_os.environ.get("D365FO_TEST_TMP", Path(tempfile.gettempdir()) / "d365fo_tests"))


def create_fixture_repo(root: Path) -> Path:
    repo_root = root / "repo"
    model_root = repo_root / "src" / "xplusplus" / "models" / "BABAccountsPayable"
    descriptor_dir = model_root / "Descriptor"
    package_dir = model_root / "BABAccountsPayable"
    (package_dir / "AxClass").mkdir(parents=True, exist_ok=True)
    (package_dir / "AxTableExtension").mkdir(parents=True, exist_ok=True)
    (package_dir / "AxDataEntityView").mkdir(parents=True, exist_ok=True)
    (package_dir / "AxSecurityPrivilege").mkdir(parents=True, exist_ok=True)
    (package_dir / "AxReport").mkdir(parents=True, exist_ok=True)
    descriptor_dir.mkdir(parents=True, exist_ok=True)

    (descriptor_dir / "BABAccountsPayable.xml").write_text(MODEL_DESCRIPTOR, encoding="utf-8")
    (package_dir / "AxClass" / "BABAssetTable_Extension.xml").write_text(CLASS_XML, encoding="utf-8")
    (package_dir / "AxTableExtension" / "AssetTable.BABAccountsPayable.xml").write_text(TABLE_EXTENSION_XML, encoding="utf-8")
    (package_dir / "AxDataEntityView" / "BABDetailledVendInvoiceDataAreaEntity.xml").write_text(DATA_ENTITY_XML, encoding="utf-8")
    (package_dir / "AxSecurityPrivilege" / "BABBFCAccount.xml").write_text(SECURITY_PRIVILEGE_XML, encoding="utf-8")
    (package_dir / "AxReport" / "BABCheque_BOA.xml").write_text(REPORT_XML, encoding="utf-8")

    with zipfile.ZipFile(model_root / "BABAccountsPayable.xref", "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ModuleReferences", "ApplicationFoundation\nApplicationSuite\n".encode("utf-16le"))
        zf.writestr("ElementReferences", ("\n".join(XREF_LINES) + "\n").encode("utf-16le"))

    return repo_root


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo_root = create_fixture_repo(self.root)
        self.rules_path = self.root / "rules.json"
        self.rules_path.write_text(json.dumps(RULES_JSON), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_rules_classify_custom_and_isv_models(self) -> None:
        from d365fo_agent.rules import load_rules

        rules = load_rules(self.rules_path)

        self.assertEqual(rules.classify_model("BABAccountsPayable"), "custom-canonical")
        self.assertEqual(rules.classify_model("BHSLicenseBase"), "isv-reference")

    def test_indexer_extracts_artifacts_and_relations(self) -> None:
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.rules import load_rules

        catalog = build_catalog(self.repo_root, load_rules(self.rules_path))

        by_name = {artifact.name: artifact for artifact in catalog.artifacts}
        self.assertIn("BABAssetTable_Extension", by_name)
        self.assertEqual(by_name["BABAssetTable_Extension"].artifact_type, "AxClass")
        self.assertTrue(by_name["BABDetailledVendInvoiceDataAreaEntity"].is_public)
        self.assertTrue(by_name["BABDetailledVendInvoiceDataAreaEntity"].data_management_enabled)
        self.assertEqual(by_name["BABBFCAccount"].label, "@BABExportBFC:BFCLedgerAccount")

        relation_pairs = {(relation.relation_type, relation.source, relation.target) for relation in catalog.relations}
        self.assertIn(("extension-of", "BABAssetTable_Extension", "AssetTable"), relation_pairs)
        self.assertIn(("extension-of", "AssetTable.BABAccountsPayable", "AssetTable"), relation_pairs)
        self.assertIn(("related-table", "AssetTable.BABAccountsPayable", "LedgerJournalTrans"), relation_pairs)
        self.assertIn(("secured-by", "BABBFCAccount", "MenuItemDisplay:BABBFCAccount"), relation_pairs)
        self.assertIn(("related-to-report", "BABCheque_BOA", "BABChequeDP_BOA"), relation_pairs)
        self.assertIn(("uses-label", "BABBFCAccount", "@BABExportBFC:BFCLedgerAccount"), relation_pairs)
        self.assertIn(("xref:MethodCall", "/Forms/BABCustVendAgingBucketLookUp/Methods/init", "/Classes/FormRun/Methods/init"), relation_pairs)


class CatalogLayoutTests(unittest.TestCase):
    """Corpus layout discovery: src/xplusplus/models, flat xplusplus/models, build-output skip."""

    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.rules_path = self.root / "rules.json"
        self.rules_path.write_text(json.dumps(RULES_JSON), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _make_flat_repo(self, repo_name: str, model: str, class_name: str) -> Path:
        # Layout WITHOUT the src/ prefix: <repo>/xplusplus/models/<Model>/<Package>/Ax*/...
        repo_root = self.root / repo_name
        model_root = repo_root / "xplusplus" / "models" / model
        (model_root / "Descriptor").mkdir(parents=True, exist_ok=True)
        (model_root / "Descriptor" / f"{model}.xml").write_text(
            MODEL_DESCRIPTOR.replace("BABAccountsPayable", model), encoding="utf-8")
        package_dir = model_root / model
        (package_dir / "AxClass").mkdir(parents=True, exist_ok=True)
        (package_dir / "AxClass" / f"{class_name}.xml").write_text(
            CLASS_XML.replace("BABAssetTable_Extension", class_name), encoding="utf-8")
        return repo_root

    def test_build_catalog_supports_flat_xplusplus_layout(self) -> None:
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.rules import load_rules

        repo_root = self._make_flat_repo("ctm", "CCICommon", "CCIHelper")
        catalog = build_catalog(repo_root, load_rules(self.rules_path))
        names = {artifact.name for artifact in catalog.artifacts}
        self.assertIn("CCIHelper", names)
        self.assertIn("CCICommon", catalog.models)

    def test_build_catalog_skips_build_output_dirs(self) -> None:
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.rules import load_rules

        repo_root = self._make_flat_repo("ctm", "CCICommon", "CCIHelper")
        model_root = repo_root / "xplusplus" / "models" / "CCICommon"
        # Compiled-metadata copies and binaries must NOT be indexed as artifacts.
        for noise in ("XppMetadata", "bin", "Resources"):
            noise_dir = model_root / noise / "CCICommon" / "AxClass"
            noise_dir.mkdir(parents=True, exist_ok=True)
            (noise_dir / "CCIHelper.xml").write_text(
                CLASS_XML.replace("BABAssetTable_Extension", "CCIHelper"), encoding="utf-8")
        catalog = build_catalog(repo_root, load_rules(self.rules_path))
        helpers = [a for a in catalog.artifacts if a.name == "CCIHelper"]
        self.assertEqual(len(helpers), 1)  # the source one only
        self.assertNotIn("XppMetadata", helpers[0].relative_path)

    def test_merge_catalogs_combines_two_corpora(self) -> None:
        from d365fo_agent.indexer import build_catalog, merge_catalogs
        from d365fo_agent.rules import load_rules

        rules = load_rules(self.rules_path)
        first = build_catalog(create_fixture_repo(self.root), rules)
        second = build_catalog(self._make_flat_repo("ctm", "CCICommon", "CCIHelper"), rules)
        merged = merge_catalogs([first, second])
        names = {artifact.name for artifact in merged.artifacts}
        self.assertIn("BABAssetTable_Extension", names)
        self.assertIn("CCIHelper", names)
        self.assertEqual(sorted(set(merged.models)), merged.models)  # sorted, no dupes
