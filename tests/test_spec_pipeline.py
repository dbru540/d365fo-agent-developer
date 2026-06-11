import io
import json
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from uuid import uuid4

from test_catalog import RULES_JSON, TEST_TEMP_ROOT, create_fixture_repo


def _graphify_available() -> bool:
    """The graph-building engine (`graphify`) is an optional external dependency.
    Tests that actually run the staging→graph pipeline are skipped when it is absent
    so the suite stays honest on machines without it (everything else still runs)."""
    import importlib.util

    return importlib.util.find_spec("graphify") is not None


_GRAPHIFY_AVAILABLE = _graphify_available()


TABLE_EXTENSION_SPEC = """# Add ledger journal reference to asset records

Artifact Family: table-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable

## Summary
Add a custom field that stores the related ledger journal transaction recid.

## Fields
- BABLedgerJournalTransRecId: RefRecId

## Acceptance Criteria
- The generated artifact extends AssetTable.
- The artifact contains the BABLedgerJournalTransRecId field.
"""


CLASS_EXTENSION_SPEC = """# Add delete override for asset table

Artifact Family: class-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable
Artifact Name: BABAssetTable_Extension

## Summary
Add a chain of command extension around delete.

## Methods
- delete(): public void

## Acceptance Criteria
- The generated class is an ExtensionOf AssetTable.
- The generated class contains a delete method stub.
"""


MULTI_ARTIFACT_SPEC = """# Add asset journal linkage support

## Artifact
Artifact Family: table-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable

### Summary
Store the related ledger journal transaction recid on the asset.

### Fields
- BABLedgerJournalTransRecId: RefRecId

## Artifact
Artifact Family: class-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable
Artifact Name: BABAssetTable_Extension
Target Kind: table

### Summary
Add a delete extension method stub around asset deletion.

### Methods
- delete(): public void
"""


PATCH_SET_SPEC = """# Add asset journal maintenance access

## Artifact
Artifact Id: asset-menu
Artifact Family: menu-item-display
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalLink
Target Object: BABAssetJournalLinkForm
Target Kind: form
Label: @BABAccountsPayable:AssetJournalLink

### Summary
Add a display menu item for the asset journal link form.

## Artifact
Artifact Id: asset-privilege
Artifact Family: security-privilege
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalLinkPrivilege

### Summary
Grant access to the asset journal link menu item.

### Entry Points
- ref:asset-menu

## Artifact
Artifact Id: asset-duty
Artifact Family: security-duty-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingMaintain

### Summary
Add the new privilege into the maintenance duty.

### Privileges
- ref:asset-privilege
"""


ACTION_ROLE_PATCH_SET_SPEC = """# Add asset journal processing access

## Artifact
Artifact Id: asset-action
Artifact Family: menu-item-action
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalProcess
Target Object: BABAssetJournalProcessService
Target Kind: class
Label: @BABAccountsPayable:AssetJournalProcess

## Artifact
Artifact Id: asset-privilege
Artifact Family: security-privilege
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalProcessPrivilege

### Entry Points
- ref:asset-action

## Artifact
Artifact Id: asset-duty
Artifact Family: security-duty-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingMaintain

### Privileges
- ref:asset-privilege

## Artifact
Artifact Id: asset-role
Artifact Family: security-role-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingManager

### Duties
- AssetAccountingMaintain

### Privileges
- ref:asset-privilege
"""


MENU_OUTPUT_SPEC = """# Add asset journal output menu item

Artifact Family: menu-item-output
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalOutput
Target Object: BABAssetJournalController
Target Kind: class
Label: @BABAccountsPayable:AssetJournalOutput
Linked Permission Object: AssetJournalReport
Linked Permission Object Child: Report
Linked Permission Type: SSRSReport
Configuration Key: Asset
"""


FORM_EXTENSION_SPEC = """# Add asset link control to asset table form

Artifact Family: form-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable
Artifact Name: AssetTable.BABAccountsPayable

## Controls
- String:BABAssetLink|AssetTable|BABAssetLink|Identification
"""


QUERY_SPEC = """# Add asset journal query

Artifact Family: query
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalQuery
Root Data Source: AssetTable
Root Table: AssetTable
Allow Cross Company: Yes
Order By: AssetId
"""


TABLE_EXTENSION_MERGE_SPEC = """# Extend existing asset table extension

Artifact Family: table-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable

## Fields
- BABAssetLinkRecId: RefRecId
"""


CLASS_EXTENSION_MERGE_SPEC = """# Extend existing asset table class extension

Artifact Family: class-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable
Artifact Name: BABAssetTable_Extension
Target Kind: table

## Methods
- babBuildAssetLink(): public void
"""


ROLE_EXTENSION_MERGE_SPEC = """# Extend existing asset accounting role

Artifact Family: security-role-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingManager

## Duties
- AssetAccountingMaintain

## Privileges
- BABAssetJournalProcessPrivilege
"""


FORM_EXTENSION_MERGE_SPEC = """# Extend existing vend table form extension

Artifact Family: form-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: VendTable
Artifact Name: VendTable.BABAccountsPayable

## Controls
- String:BABAssetLink|VendTable|BABAssetLink|Identification
"""


QUERY_MERGE_SPEC = """# Extend existing company lookup query

Artifact Family: query
Model: BABAccountsPayable
Package: BABVendorAgingBalance
Artifact Name: BABCompanyLookupQuery
Root Data Source: CompanyInfo
Root Table: CompanyInfo
Allow Cross Company: Yes
Order By: DataArea
"""


SERVICE_SPEC = """# Add asset journal service

Artifact Family: service
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalService
Service Class: BABAssetJournalServiceClass

## Operations
- getAssetJournalLink|getAssetJournalLink
"""


SERVICE_GROUP_SPEC = """# Add asset journal service group

Artifact Family: service-group
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalServiceGroup
Auto Deploy: Yes

## Services
- BABAssetJournalService
"""


SERVICE_PATCH_SET_SPEC = """# Add asset journal service integration

## Artifact
Artifact Id: asset-service
Artifact Family: service
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalService
Service Class: BABAssetJournalServiceClass

### Operations
- getAssetJournalLink|getAssetJournalLink

## Artifact
Artifact Id: asset-service-group
Artifact Family: service-group
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalServiceGroup
Auto Deploy: Yes

### Services
- ref:asset-service
"""


SERVICE_MERGE_SPEC = """# Extend existing asset journal service

Artifact Family: service
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalService
Service Class: BABAssetJournalServiceClass

## Operations
- postAssetJournalLink|postAssetJournalLink
"""


SERVICE_GROUP_MERGE_SPEC = """# Extend existing asset journal service group

Artifact Family: service-group
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalServiceGroup
Auto Deploy: Yes

## Services
- BABAssetJournalService
- BABAssetJournalSyncService
"""


def create_packageslocal_fixture(root: Path) -> Path:
    packages_root = root / "packages"
    service_dir = packages_root / "ApplicationFoundation" / "ApplicationFoundation" / "AxService"
    service_group_dir = packages_root / "ApplicationFoundation" / "ApplicationFoundation" / "AxServiceGroup"
    menu_item_dir = packages_root / "ApplicationFoundation" / "ApplicationFoundation" / "AxMenuItemDisplay"
    security_privilege_dir = packages_root / "ApplicationFoundation" / "ApplicationFoundation" / "AxSecurityPrivilege"
    query_dir = packages_root / "ApplicationFoundation" / "ApplicationFoundation" / "AxQuery"
    table_extension_dir = packages_root / "ApplicationFoundation" / "ApplicationFoundation" / "AxTableExtension"
    form_extension_dir = packages_root / "ApplicationFoundation" / "ApplicationFoundation" / "AxFormExtension"
    entity_dir = packages_root / "ApplicationFoundation" / "ApplicationFoundation" / "AxDataEntityView"
    descriptor_dir = packages_root / "ApplicationFoundation" / "Descriptor"
    class_dir = packages_root / "ApplicationFoundation" / "ApplicationFoundation" / "AxClass"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_group_dir.mkdir(parents=True, exist_ok=True)
    menu_item_dir.mkdir(parents=True, exist_ok=True)
    security_privilege_dir.mkdir(parents=True, exist_ok=True)
    query_dir.mkdir(parents=True, exist_ok=True)
    table_extension_dir.mkdir(parents=True, exist_ok=True)
    form_extension_dir.mkdir(parents=True, exist_ok=True)
    entity_dir.mkdir(parents=True, exist_ok=True)
    descriptor_dir.mkdir(parents=True, exist_ok=True)
    class_dir.mkdir(parents=True, exist_ok=True)

    (descriptor_dir / "ApplicationFoundation.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxModelInfo xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>ApplicationFoundation</Name>
  <Publisher>Microsoft</Publisher>
</AxModelInfo>
""",
        encoding="utf-8",
    )

    (service_dir / "AifUserSessionService.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxService xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>AifUserSessionService</Name>
  <Class>AifUserSessionService</Class>
  <ExternalName>AifUserSessionService</ExternalName>
  <ServiceOperations>
    <AxServiceOperation>
      <Name>getUserSession</Name>
      <Method>getUserSession</Method>
    </AxServiceOperation>
  </ServiceOperations>
</AxService>
""",
        encoding="utf-8",
    )

    (service_group_dir / "UserSessionService.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxServiceGroup xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>UserSessionService</Name>
  <AutoDeploy>Yes</AutoDeploy>
  <Services>
    <AxServiceGroupService>
      <Name>AifUserSessionService</Name>
      <Service>AifUserSessionService</Service>
    </AxServiceGroupService>
  </Services>
</AxServiceGroup>
""",
        encoding="utf-8",
    )

    (class_dir / "AifUserSessionService.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxClass xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>AifUserSessionService</Name>
  <SourceCode>
    <Declaration><![CDATA[
class AifUserSessionService
{
}
]]></Declaration>
  </SourceCode>
</AxClass>
""",
        encoding="utf-8",
    )

    (menu_item_dir / "AifUserSessionMenu.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxMenuItemDisplay xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="Microsoft.Dynamics.AX.Metadata.V1">
  <Name>AifUserSessionMenu</Name>
  <Object>AifUserSessionForm</Object>
</AxMenuItemDisplay>
""",
        encoding="utf-8",
    )

    (security_privilege_dir / "AifUserSessionPrivilege.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxSecurityPrivilege xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>AifUserSessionPrivilege</Name>
  <EntryPoints>
    <AxSecurityEntryPointReference>
      <Name>AifUserSessionMenu</Name>
      <ObjectName>AifUserSessionMenu</ObjectName>
      <ObjectType>MenuItemDisplay</ObjectType>
    </AxSecurityEntryPointReference>
  </EntryPoints>
</AxSecurityPrivilege>
""",
        encoding="utf-8",
    )

    (query_dir / "AifUserSessionQuery.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxQuery xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="" i:type="AxQuerySimple">
  <Name>AifUserSessionQuery</Name>
  <AllowCrossCompany>Yes</AllowCrossCompany>
  <DataSources>
    <AxQuerySimpleRootDataSource>
      <Name>UserInfo</Name>
      <Table>UserInfo</Table>
      <DataSources />
      <DerivedDataSources />
      <Fields />
      <Ranges />
      <GroupBy />
      <Having />
      <OrderBy />
    </AxQuerySimpleRootDataSource>
  </DataSources>
</AxQuery>
""",
        encoding="utf-8",
    )

    (table_extension_dir / "UserInfo.ApplicationFoundation.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>UserInfo.ApplicationFoundation</Name>
</AxTableExtension>
""",
        encoding="utf-8",
    )

    (form_extension_dir / "UserInfo.ApplicationFoundation.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxFormExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="Microsoft.Dynamics.AX.Metadata.V6">
  <Name>UserInfo.ApplicationFoundation</Name>
</AxFormExtension>
""",
        encoding="utf-8",
    )

    (entity_dir / "AifUserSessionEntity.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AxDataEntityView xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>AifUserSessionEntity</Name>
  <PublicEntityName>AifUserSession</PublicEntityName>
  <ViewMetadata>
    <Name>Metadata</Name>
    <DataSources>
      <AxQuerySimpleRootDataSource>
        <Name>UserInfo</Name>
        <Table>UserInfo</Table>
      </AxQuerySimpleRootDataSource>
    </DataSources>
  </ViewMetadata>
</AxDataEntityView>
""",
        encoding="utf-8",
    )
    return packages_root


class SpecPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo_root = create_fixture_repo(self.root)
        self.packages_root = create_packageslocal_fixture(self.root)
        self.rules_path = self.root / "rules.json"
        self.rules_path.write_text(json.dumps(RULES_JSON), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_parse_spec_extracts_metadata_and_sections(self) -> None:
        from d365fo_agent.specs import parse_spec_text

        spec = parse_spec_text(TABLE_EXTENSION_SPEC)

        self.assertEqual(spec.title, "Add ledger journal reference to asset records")
        self.assertEqual(spec.metadata["artifact_family"], "table-extension")
        self.assertEqual(spec.metadata["target_object"], "AssetTable")
        self.assertIn("BABLedgerJournalTransRecId: RefRecId", spec.sections["fields"])

    def test_parse_multi_artifact_spec_extracts_artifact_blocks(self) -> None:
        from d365fo_agent.specs import parse_spec_text

        spec = parse_spec_text(MULTI_ARTIFACT_SPEC)

        self.assertEqual(spec.title, "Add asset journal linkage support")
        self.assertEqual(len(spec.artifact_specs), 2)
        self.assertEqual(spec.artifact_specs[0].metadata["artifact_family"], "table-extension")
        self.assertEqual(spec.artifact_specs[1].metadata["artifact_family"], "class-extension")
        self.assertIn("BABLedgerJournalTransRecId: RefRecId", spec.artifact_specs[0].sections["fields"])
        self.assertIn("delete(): public void", spec.artifact_specs[1].sections["methods"])

    def test_build_artifact_plan_returns_expected_output_path(self) -> None:
        from d365fo_agent.specs import build_artifact_plan, parse_spec_text

        spec = parse_spec_text(TABLE_EXTENSION_SPEC)
        plan = build_artifact_plan(spec)

        self.assertEqual(plan.family, "table-extension")
        self.assertEqual(plan.artifact_type, "AxTableExtension")
        self.assertEqual(plan.target_object, "AssetTable")
        self.assertEqual(
            plan.output_path,
            "src/xplusplus/models/BABAccountsPayable/BABAccountsPayable/AxTableExtension/AssetTable.BABAccountsPayable.xml",
        )
        self.assertEqual(plan.fields[0]["name"], "BABLedgerJournalTransRecId")

    def test_build_artifact_plans_returns_multiple_outputs(self) -> None:
        from d365fo_agent.specs import build_artifact_plans, parse_spec_text

        spec = parse_spec_text(MULTI_ARTIFACT_SPEC)
        plans = build_artifact_plans(spec)

        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[0].artifact_type, "AxTableExtension")
        self.assertEqual(plans[1].artifact_type, "AxClass")
        self.assertEqual(
            plans[1].output_path,
            "src/xplusplus/models/BABAccountsPayable/BABAccountsPayable/AxClass/BABAssetTable_Extension.xml",
        )

    def test_build_generation_bundle_picks_relevant_examples(self) -> None:
        from d365fo_agent.generator import build_generation_bundle
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.rules import load_rules
        from d365fo_agent.specs import build_artifact_plan, parse_spec_text

        catalog = build_catalog(self.repo_root, load_rules(self.rules_path))
        spec = parse_spec_text(TABLE_EXTENSION_SPEC)
        plan = build_artifact_plan(spec)
        bundle = build_generation_bundle(spec, plan, catalog, self.repo_root, example_limit=2)

        self.assertEqual(bundle["artifact_plan"]["artifact_type"], "AxTableExtension")
        self.assertEqual(bundle["examples"][0]["artifact"]["name"], "AssetTable.BABAccountsPayable")
        self.assertIn("BABLedgerJournalTransRecId", bundle["examples"][0]["content"])

    def test_generate_from_spec_writes_table_extension_xml(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "table-extension.md"
        output_dir = self.root / "generated"
        spec_path.write_text(TABLE_EXTENSION_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_file = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxTableExtension" / "AssetTable.BABAccountsPayable.xml"
        self.assertEqual(result["artifact_plan"]["family"], "table-extension")
        self.assertTrue(generated_file.exists())
        xml = generated_file.read_text(encoding="utf-8")
        self.assertIn("<Name>AssetTable.BABAccountsPayable</Name>", xml)
        self.assertIn("<Name>BABLedgerJournalTransRecId</Name>", xml)

    def test_generate_from_multi_artifact_spec_writes_multiple_files(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "multi-artifact.md"
        output_dir = self.root / "generated-multi"
        spec_path.write_text(MULTI_ARTIFACT_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_table = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxTableExtension" / "AssetTable.BABAccountsPayable.xml"
        generated_class = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxClass" / "BABAssetTable_Extension.xml"

        self.assertEqual(len(result["generated_files"]), 2)
        self.assertTrue(generated_table.exists())
        self.assertTrue(generated_class.exists())
        self.assertIn("[ExtensionOf(tableStr(AssetTable))]", generated_class.read_text(encoding="utf-8"))

    def test_patch_set_spec_resolves_cross_artifact_references(self) -> None:
        from d365fo_agent.specs import build_artifact_plans, parse_spec_text

        spec = parse_spec_text(PATCH_SET_SPEC)
        plans = build_artifact_plans(spec)

        self.assertEqual(len(plans), 3)
        self.assertEqual(plans[0].artifact_type, "AxMenuItemDisplay")
        self.assertEqual(plans[1].artifact_type, "AxSecurityPrivilege")
        self.assertEqual(plans[2].artifact_type, "AxSecurityDutyExtension")
        self.assertEqual(plans[1].entry_points[0]["object_type"], "MenuItemDisplay")
        self.assertEqual(plans[1].entry_points[0]["object_name"], "BABAssetJournalLink")
        self.assertEqual(plans[2].privileges[0]["name"], "BABAssetJournalLinkPrivilege")

    def test_generate_patch_set_writes_menu_privilege_and_duty_files(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "patch-set.md"
        output_dir = self.root / "generated-patch-set"
        spec_path.write_text(PATCH_SET_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_menu = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxMenuItemDisplay" / "BABAssetJournalLink.xml"
        generated_privilege = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxSecurityPrivilege" / "BABAssetJournalLinkPrivilege.xml"
        generated_duty = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxSecurityDutyExtension" / "AssetAccountingMaintain.BABAccountsPayable.xml"

        self.assertEqual(len(result["generated_files"]), 3)
        self.assertTrue(generated_menu.exists())
        self.assertTrue(generated_privilege.exists())
        self.assertTrue(generated_duty.exists())
        self.assertIn("<Object>BABAssetJournalLinkForm</Object>", generated_menu.read_text(encoding="utf-8"))
        self.assertIn("<ObjectName>BABAssetJournalLink</ObjectName>", generated_privilege.read_text(encoding="utf-8"))
        self.assertIn("<Name>BABAssetJournalLinkPrivilege</Name>", generated_duty.read_text(encoding="utf-8"))

    def test_action_patch_set_resolves_role_dependencies(self) -> None:
        from d365fo_agent.specs import build_artifact_plans, parse_spec_text

        spec = parse_spec_text(ACTION_ROLE_PATCH_SET_SPEC)
        plans = build_artifact_plans(spec)

        self.assertEqual(len(plans), 4)
        self.assertEqual(plans[0].artifact_type, "AxMenuItemAction")
        self.assertEqual(plans[3].artifact_type, "AxSecurityRoleExtension")
        self.assertEqual(plans[1].entry_points[0]["object_type"], "MenuItemAction")
        self.assertEqual(plans[1].entry_points[0]["object_name"], "BABAssetJournalProcess")
        self.assertEqual(plans[3].duties[0]["name"], "AssetAccountingMaintain")
        self.assertEqual(plans[3].privileges[0]["name"], "BABAssetJournalProcessPrivilege")

    def test_generate_action_role_patch_set_writes_all_files(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "action-role-patch-set.md"
        output_dir = self.root / "generated-action-role-patch-set"
        spec_path.write_text(ACTION_ROLE_PATCH_SET_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_action = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxMenuItemAction" / "BABAssetJournalProcess.xml"
        generated_role = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxSecurityRoleExtension" / "AssetAccountingManager.BABAccountsPayable.xml"

        self.assertEqual(len(result["generated_files"]), 4)
        self.assertTrue(generated_action.exists())
        self.assertTrue(generated_role.exists())
        self.assertIn("<ObjectType>Class</ObjectType>", generated_action.read_text(encoding="utf-8"))
        self.assertIn("<Name>AssetAccountingMaintain</Name>", generated_role.read_text(encoding="utf-8"))
        self.assertIn("<Name>BABAssetJournalProcessPrivilege</Name>", generated_role.read_text(encoding="utf-8"))

    def test_generate_menu_item_output_xml(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "menu-output.md"
        output_dir = self.root / "generated-menu-output"
        spec_path.write_text(MENU_OUTPUT_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_output = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxMenuItemOutput" / "BABAssetJournalOutput.xml"

        self.assertEqual(result["artifact_plan"]["family"], "menu-item-output")
        self.assertTrue(generated_output.exists())
        xml = generated_output.read_text(encoding="utf-8")
        self.assertIn("<ObjectType>Class</ObjectType>", xml)
        self.assertIn("<LinkedPermissionObject>AssetJournalReport</LinkedPermissionObject>", xml)
        self.assertIn("<LinkedPermissionType>SSRSReport</LinkedPermissionType>", xml)

    def test_generate_form_extension_xml(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "form-extension.md"
        output_dir = self.root / "generated-form-extension"
        spec_path.write_text(FORM_EXTENSION_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_form_extension = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxFormExtension" / "AssetTable.BABAccountsPayable.xml"
        xml = generated_form_extension.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_plan"]["family"], "form-extension")
        self.assertTrue(generated_form_extension.exists())
        self.assertIn("<Parent>Identification</Parent>", xml)
        self.assertIn("<DataField>BABAssetLink</DataField>", xml)

    def test_generate_query_xml(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "query.md"
        output_dir = self.root / "generated-query"
        spec_path.write_text(QUERY_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_query = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxQuery" / "BABAssetJournalQuery.xml"
        xml = generated_query.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_plan"]["family"], "query")
        self.assertTrue(generated_query.exists())
        self.assertIn("<AllowCrossCompany>Yes</AllowCrossCompany>", xml)
        self.assertIn("<Table>AssetTable</Table>", xml)
        self.assertIn("<Field>AssetId</Field>", xml)

    def test_merge_existing_table_extension_preserves_existing_relations(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "table-extension-merge.md"
        output_dir = self.root / "generated-table-extension-merge"
        spec_path.write_text(TABLE_EXTENSION_MERGE_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_table = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxTableExtension" / "AssetTable.BABAccountsPayable.xml"
        xml = generated_table.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_results"][0]["generation_mode"], "merged")
        self.assertIn("<Name>BABLedgerJournalTransRecId</Name>", xml)
        self.assertIn("<Name>BABAssetLinkRecId</Name>", xml)
        self.assertIn("<RelatedTable>LedgerJournalTrans</RelatedTable>", xml)

    def test_merge_existing_class_extension_preserves_existing_methods(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "class-extension-merge.md"
        output_dir = self.root / "generated-class-extension-merge"
        spec_path.write_text(CLASS_EXTENSION_MERGE_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_class = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxClass" / "BABAssetTable_Extension.xml"
        xml = generated_class.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_results"][0]["generation_mode"], "merged")
        self.assertIn("<Name>delete</Name>", xml)
        self.assertIn("<Name>babBuildAssetLink</Name>", xml)

    def test_merge_existing_role_extension_adds_privilege(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        role_extension_dir = self.repo_root / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxSecurityRoleExtension"
        role_extension_dir.mkdir(parents=True, exist_ok=True)
        role_extension = role_extension_dir / "AssetAccountingManager.BABAccountsPayable.xml"
        role_extension.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<AxSecurityRoleExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>AssetAccountingManager.BABAccountsPayable</Name>
\t<DirectAccessPermissions />
\t<Duties>
\t\t<AxSecurityDutyReference>
\t\t\t<Name>AssetAccountingMaintain</Name>
\t\t</AxSecurityDutyReference>
\t</Duties>
\t<Privileges />
\t<PropertyModifications />
</AxSecurityRoleExtension>
""",
            encoding="utf-8",
        )

        spec_path = self.root / "role-extension-merge.md"
        output_dir = self.root / "generated-role-extension-merge"
        spec_path.write_text(ROLE_EXTENSION_MERGE_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_role = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxSecurityRoleExtension" / "AssetAccountingManager.BABAccountsPayable.xml"
        xml = generated_role.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_results"][0]["generation_mode"], "merged")
        self.assertIn("<Name>AssetAccountingMaintain</Name>", xml)
        self.assertIn("<Name>BABAssetJournalProcessPrivilege</Name>", xml)

    def test_merge_existing_form_extension_adds_control(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        form_extension_dir = self.repo_root / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxFormExtension"
        form_extension_dir.mkdir(parents=True, exist_ok=True)
        form_extension = form_extension_dir / "VendTable.BABAccountsPayable.xml"
        form_extension.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<AxFormExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="Microsoft.Dynamics.AX.Metadata.V6">
\t<Name>VendTable.BABAccountsPayable</Name>
\t<ControlModifications />
\t<Controls />
\t<DataSourceModifications />
\t<DataSourceReferences />
\t<DataSources />
\t<Parts />
\t<PropertyModifications />
</AxFormExtension>
""",
            encoding="utf-8",
        )

        spec_path = self.root / "form-extension-merge.md"
        output_dir = self.root / "generated-form-extension-merge"
        spec_path.write_text(FORM_EXTENSION_MERGE_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_form_extension = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxFormExtension" / "VendTable.BABAccountsPayable.xml"
        xml = generated_form_extension.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_results"][0]["generation_mode"], "merged")
        self.assertIn("<Name>BABAssetLink</Name>", xml)
        self.assertIn("<Parent>Identification</Parent>", xml)

    def test_merge_existing_query_adds_order_by(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        query_dir = self.repo_root / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABVendorAgingBalance" / "AxQuery"
        query_dir.mkdir(parents=True, exist_ok=True)
        query_file = query_dir / "BABCompanyLookupQuery.xml"
        query_file.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<AxQuery xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="" i:type="AxQuerySimple">
\t<Name>BABCompanyLookupQuery</Name>
\t<SourceCode>
\t\t<Methods>
\t\t\t<Method>
\t\t\t\t<Name>classDeclaration</Name>
\t\t\t\t<Source><![CDATA[
[Query]
public class BABCompanyLookupQuery extends QueryRun
{
}
]]></Source>
\t\t\t</Method>
\t\t</Methods>
\t</SourceCode>
\t<DataSources>
\t\t<AxQuerySimpleRootDataSource>
\t\t\t<Name>CompanyInfo</Name>
\t\t\t<DynamicFields>Yes</DynamicFields>
\t\t\t<Table>CompanyInfo</Table>
\t\t\t<DataSources />
\t\t\t<DerivedDataSources />
\t\t\t<Fields />
\t\t\t<Ranges />
\t\t\t<GroupBy />
\t\t\t<Having />
\t\t\t<OrderBy />
\t\t</AxQuerySimpleRootDataSource>
\t</DataSources>
</AxQuery>
""",
            encoding="utf-8",
        )

        spec_path = self.root / "query-merge.md"
        output_dir = self.root / "generated-query-merge"
        spec_path.write_text(QUERY_MERGE_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_query = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABVendorAgingBalance" / "AxQuery" / "BABCompanyLookupQuery.xml"
        xml = generated_query.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_results"][0]["generation_mode"], "merged")
        self.assertIn("<AllowCrossCompany>Yes</AllowCrossCompany>", xml)
        self.assertIn("<Field>DataArea</Field>", xml)

    def test_generate_service_xml(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "service.md"
        output_dir = self.root / "generated-service"
        spec_path.write_text(SERVICE_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_service = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxService" / "BABAssetJournalService.xml"
        xml = generated_service.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_plan"]["family"], "service")
        self.assertTrue(generated_service.exists())
        self.assertIn("<Class>BABAssetJournalServiceClass</Class>", xml)
        self.assertIn("<Method>getAssetJournalLink</Method>", xml)

    def test_generate_service_group_xml(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        spec_path = self.root / "service-group.md"
        output_dir = self.root / "generated-service-group"
        spec_path.write_text(SERVICE_GROUP_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_group = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxServiceGroup" / "BABAssetJournalServiceGroup.xml"
        xml = generated_group.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_plan"]["family"], "service-group")
        self.assertTrue(generated_group.exists())
        self.assertIn("<AutoDeploy>Yes</AutoDeploy>", xml)
        self.assertIn("<Name>BABAssetJournalService</Name>", xml)

    def test_service_patch_set_resolves_service_group_reference(self) -> None:
        from d365fo_agent.specs import build_artifact_plans, parse_spec_text

        spec = parse_spec_text(SERVICE_PATCH_SET_SPEC)
        plans = build_artifact_plans(spec)

        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[0].artifact_type, "AxService")
        self.assertEqual(plans[1].artifact_type, "AxServiceGroup")
        self.assertEqual(plans[1].services[0]["name"], "BABAssetJournalService")

    def test_merge_existing_service_adds_operation(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        service_dir = self.repo_root / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxService"
        service_dir.mkdir(parents=True, exist_ok=True)
        service_file = service_dir / "BABAssetJournalService.xml"
        service_file.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<AxService xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>BABAssetJournalService</Name>
\t<Class>BABAssetJournalServiceClass</Class>
\t<Operations>
\t\t<AxServiceOperation>
\t\t\t<Name>getAssetJournalLink</Name>
\t\t\t<Method>getAssetJournalLink</Method>
\t\t</AxServiceOperation>
\t</Operations>
</AxService>
""",
            encoding="utf-8",
        )

        spec_path = self.root / "service-merge.md"
        output_dir = self.root / "generated-service-merge"
        spec_path.write_text(SERVICE_MERGE_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_service = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxService" / "BABAssetJournalService.xml"
        xml = generated_service.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_results"][0]["generation_mode"], "merged")
        self.assertIn("<Name>getAssetJournalLink</Name>", xml)
        self.assertIn("<Name>postAssetJournalLink</Name>", xml)

    def test_merge_existing_service_group_adds_service_reference(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        service_group_dir = self.repo_root / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxServiceGroup"
        service_group_dir.mkdir(parents=True, exist_ok=True)
        service_group_file = service_group_dir / "BABAssetJournalServiceGroup.xml"
        service_group_file.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<AxServiceGroup xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>BABAssetJournalServiceGroup</Name>
\t<AutoDeploy>Yes</AutoDeploy>
\t<Services>
\t\t<AxServiceReference>
\t\t\t<Name>BABAssetJournalService</Name>
\t\t</AxServiceReference>
\t</Services>
</AxServiceGroup>
""",
            encoding="utf-8",
        )

        spec_path = self.root / "service-group-merge.md"
        output_dir = self.root / "generated-service-group-merge"
        spec_path.write_text(SERVICE_GROUP_MERGE_SPEC, encoding="utf-8")

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        generated_group = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxServiceGroup" / "BABAssetJournalServiceGroup.xml"
        xml = generated_group.read_text(encoding="utf-8")

        self.assertEqual(result["artifact_results"][0]["generation_mode"], "merged")
        self.assertIn("<Name>BABAssetJournalService</Name>", xml)
        self.assertIn("<Name>BABAssetJournalSyncService</Name>", xml)

    def test_packageslocal_inventory_detects_service_assets(self) -> None:
        from d365fo_agent.packageslocal_export import inventory_packageslocal

        inventory = inventory_packageslocal(self.packages_root)

        self.assertEqual(inventory["package_count"], 1)
        self.assertEqual(inventory["artifact_counts"]["AxService"], 1)
        self.assertEqual(inventory["artifact_counts"]["AxServiceGroup"], 1)
        self.assertEqual(inventory["artifact_counts"]["AxClass"], 1)

    def test_packageslocal_inventory_accepts_single_package_path(self) -> None:
        from d365fo_agent.packageslocal_export import inventory_packageslocal

        inventory = inventory_packageslocal(self.packages_root / "ApplicationFoundation")

        self.assertEqual(inventory["package_count"], 1)
        self.assertEqual(inventory["packages"][0]["package_name"], "ApplicationFoundation")

    def test_export_packageslocal_graphify_staging_writes_markdown_and_json(self) -> None:
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify

        output_dir = self.root / "graphify-staging"
        manifest = export_packageslocal_to_graphify(self.packages_root, output_dir)

        package_md = output_dir / "raw" / "packages" / "ApplicationFoundation.md"
        service_md = output_dir / "raw" / "artifacts" / "ApplicationFoundation__AxService__AifUserSessionService.md"
        summary_json = output_dir / "graphify-staging-manifest.json"

        self.assertEqual(manifest["package_count"], 1)
        self.assertTrue(package_md.exists())
        self.assertTrue(service_md.exists())
        self.assertTrue(summary_json.exists())
        self.assertIn("AifUserSessionService", service_md.read_text(encoding="utf-8"))
        self.assertIn("UserSessionService", package_md.read_text(encoding="utf-8"))
        self.assertIn("getUserSession", service_md.read_text(encoding="utf-8"))

    def test_export_packageslocal_cli_writes_staging_manifest(self) -> None:
        from d365fo_agent.cli import main

        output_dir = self.root / "graphify-cli-staging"
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "export-packageslocal-graphify",
                    "--packages-root",
                    str(self.packages_root),
                    "--output-dir",
                    str(output_dir),
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["package_count"], 1)
        self.assertTrue((output_dir / "graphify-staging-manifest.json").exists())

    def test_run_graphify_staging_writes_graph_outputs(self) -> None:
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")

        staging_dir = self.root / "graphify-staging-runner"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        output_dir = self.root / "graphify-run-output"

        result = run_graphify_staging(staging_dir, output_dir, include_html=True)

        self.assertGreaterEqual(result["node_count"], 3)
        self.assertGreaterEqual(result["edge_count"], 2)
        self.assertTrue((output_dir / "graph.json").exists())
        self.assertTrue((output_dir / "GRAPH_REPORT.md").exists())
        self.assertTrue((output_dir / "graph.html").exists())

        graph_payload = json.loads((output_dir / "graph.json").read_text(encoding="utf-8"))
        labels = {node.get("label") for node in graph_payload["nodes"]}
        self.assertIn("ApplicationFoundation", labels)
        self.assertIn("AifUserSessionService", labels)
        self.assertIn("UserSessionService", labels)

        edge_triples = {(edge["source"], edge["target"], edge.get("relation")) for edge in graph_payload["links"]}
        self.assertIn(
            (
                "artifact:ApplicationFoundation:AxServiceGroup:UserSessionService",
                "artifact:ApplicationFoundation:AxService:AifUserSessionService",
                "groups-service",
            ),
            edge_triples,
        )
        self.assertIn(
            (
                "artifact:ApplicationFoundation:AxService:AifUserSessionService",
                "class:ApplicationFoundation:AifUserSessionService",
                "implemented-by",
            ),
            edge_triples,
        )
        self.assertIn(
            (
                "artifact:ApplicationFoundation:AxMenuItemDisplay:AifUserSessionMenu",
                "form-ref:AifUserSessionForm",
                "targets-form",
            ),
            edge_triples,
        )
        self.assertIn(
            (
                "artifact:ApplicationFoundation:AxSecurityPrivilege:AifUserSessionPrivilege",
                "artifact:ApplicationFoundation:AxMenuItemDisplay:AifUserSessionMenu",
                "grants-access-to",
            ),
            edge_triples,
        )
        self.assertIn(
            (
                "artifact:ApplicationFoundation:AxQuery:AifUserSessionQuery",
                "table-ref:ApplicationFoundation:UserInfo",
                "queries-table",
            ),
            edge_triples,
        )
        self.assertIn(
            (
                "artifact:ApplicationFoundation:AxTableExtension:UserInfo.ApplicationFoundation",
                "table-ref:ApplicationFoundation:UserInfo",
                "extends-table",
            ),
            edge_triples,
        )
        self.assertIn(
            (
                "artifact:ApplicationFoundation:AxFormExtension:UserInfo.ApplicationFoundation",
                "form-ref:UserInfo",
                "extends-form",
            ),
            edge_triples,
        )
        self.assertIn(
            (
                "artifact:ApplicationFoundation:AxDataEntityView:AifUserSessionEntity",
                "table-ref:ApplicationFoundation:UserInfo",
                "entity-root-table",
            ),
            edge_triples,
        )

    def test_run_graphify_staging_cli_writes_outputs(self) -> None:
        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.cli import main
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify

        staging_dir = self.root / "graphify-staging-cli-runner"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        output_dir = self.root / "graphify-cli-run-output"

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "run-graphify-staging",
                    "--staging-dir",
                    str(staging_dir),
                    "--output-dir",
                    str(output_dir),
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue((output_dir / "graph.json").exists())
        self.assertTrue((output_dir / "GRAPH_REPORT.md").exists())
        self.assertGreaterEqual(payload["node_count"], 3)

    def test_graph_queries_return_related_artifacts(self) -> None:
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.graph_query import GraphIndex
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify

        staging_dir = self.root / "graphify-staging-graph-query"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        output_dir = self.root / "graphify-run-graph-query"
        run_graphify_staging(staging_dir, output_dir, include_html=False)

        graph_index = GraphIndex(output_dir / "graph.json")
        neighbors = graph_index.related_artifact_labels("AifUserSessionService")

        self.assertIn("UserSessionService", neighbors)
        self.assertIn("AifUserSessionService", neighbors)

    def test_build_generation_bundle_can_include_graph_examples(self) -> None:
        from d365fo_agent.generator import build_generation_bundle
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.graph_query import GraphIndex
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify
        from d365fo_agent.rules import load_rules
        from d365fo_agent.specs import build_artifact_plan, parse_spec_text

        catalog = build_catalog(self.repo_root, load_rules(self.rules_path))
        spec = parse_spec_text(TABLE_EXTENSION_SPEC)
        plan = build_artifact_plan(spec)

        staging_dir = self.root / "graphify-staging-bundle"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        graph_output_dir = self.root / "graphify-run-bundle"
        run_graphify_staging(staging_dir, graph_output_dir, include_html=False)
        graph_index = GraphIndex(graph_output_dir / "graph.json")

        bundle = build_generation_bundle(
            spec,
            plan,
            catalog,
            self.repo_root,
            example_limit=2,
            graph_index=graph_index,
            graph_query="AifUserSessionService",
        )

        self.assertIn("graph_examples", bundle)
        self.assertGreaterEqual(len(bundle["graph_examples"]), 1)
        self.assertEqual(bundle["graph_examples"][0]["label"], "AifUserSessionService")

    def test_graph_related_artifact_can_be_promoted_into_examples(self) -> None:
        from d365fo_agent.generator import build_generation_bundle
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.graph_query import GraphIndex
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify
        from d365fo_agent.rules import load_rules
        from d365fo_agent.specs import parse_spec_text, build_artifact_plan

        catalog = build_catalog(self.repo_root, load_rules(self.rules_path))
        spec = parse_spec_text(SERVICE_GROUP_SPEC)
        plan = build_artifact_plan(spec)

        staging_dir = self.root / "graphify-staging-service-hybrid"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        graph_output_dir = self.root / "graphify-run-service-hybrid"
        run_graphify_staging(staging_dir, graph_output_dir, include_html=False)
        graph_index = GraphIndex(graph_output_dir / "graph.json")

        bundle = build_generation_bundle(
            spec,
            plan,
            catalog,
            self.repo_root,
            example_limit=3,
            graph_index=graph_index,
            graph_query="UserSessionService",
        )

        example_names = [example["artifact"]["name"] for example in bundle["examples"]]
        self.assertIn("AifUserSessionService", example_names)

    def test_discover_graph_path_finds_parent_omx_graph(self) -> None:
        from d365fo_agent.graph_query import discover_graph_path
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify

        staging_dir = self.root / ".omx" / "graphify-staging-auto"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        graph_output_dir = self.root / ".omx" / "graphify-run-auto"
        run_graphify_staging(staging_dir, graph_output_dir, include_html=False)

        discovered = discover_graph_path(self.root / "repo")

        self.assertIsNotNone(discovered)
        self.assertEqual(discovered.name, "graph.json")

    def test_analyze_spec_cli_can_use_explicit_graph(self) -> None:
        from d365fo_agent.cli import main
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify

        spec_path = self.root / "table-extension-explicit.md"
        spec_path.write_text(TABLE_EXTENSION_SPEC, encoding="utf-8")
        staging_dir = self.root / "graphify-staging-explicit"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        graph_output_dir = self.root / "graphify-run-explicit"
        run_graphify_staging(staging_dir, graph_output_dir, include_html=False)

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "analyze-spec",
                    "--repo-root",
                    str(self.repo_root),
                    "--rules",
                    str(self.rules_path),
                    "--spec",
                    str(spec_path),
                    "--graph",
                    str(graph_output_dir / "graph.json"),
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertIn("graph_examples", payload["artifacts"][0])

    def test_generate_from_spec_file_uses_auto_discovered_graph(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify

        spec_path = self.root / "table-extension.md"
        spec_path.write_text(TABLE_EXTENSION_SPEC, encoding="utf-8")

        staging_dir = self.root / ".omx" / "graphify-staging-auto-generate"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        graph_output_dir = self.root / ".omx" / "graphify-run-auto-generate"
        run_graphify_staging(staging_dir, graph_output_dir, include_html=False)

        output_dir = self.root / "generated-auto-graph"
        generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        self.assertIn("artifacts", json.loads((output_dir / "generation-bundle.json").read_text(encoding="utf-8")))
        bundle = json.loads((output_dir / "generation-bundle.json").read_text(encoding="utf-8"))
        self.assertIn("graph_examples", bundle["artifacts"][0])

    def test_hybrid_ranking_dedupes_example_names(self) -> None:
        from d365fo_agent.generator import build_generation_bundle
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.graph_query import GraphIndex
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify
        from d365fo_agent.rules import load_rules
        from d365fo_agent.specs import build_artifact_plan, parse_spec_text

        catalog = build_catalog(self.repo_root, load_rules(self.rules_path))
        spec = parse_spec_text(SERVICE_GROUP_SPEC)
        plan = build_artifact_plan(spec)

        staging_dir = self.root / "graphify-staging-dedupe"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        graph_output_dir = self.root / "graphify-run-dedupe"
        run_graphify_staging(staging_dir, graph_output_dir, include_html=False)
        graph_index = GraphIndex(graph_output_dir / "graph.json")

        bundle = build_generation_bundle(
            spec, plan, catalog, self.repo_root, example_limit=3,
            graph_index=graph_index, graph_query="UserSessionService",
        )

        names = [ex["artifact"]["name"] for ex in bundle["examples"]]
        self.assertEqual(len(names), len(set(names)))

    def test_strong_catalog_match_beats_unrelated_graph_neighbor(self) -> None:
        from d365fo_agent.generator import build_generation_bundle
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.graph_query import GraphIndex
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify
        from d365fo_agent.rules import load_rules
        from d365fo_agent.specs import build_artifact_plan, parse_spec_text

        catalog = build_catalog(self.repo_root, load_rules(self.rules_path))
        spec = parse_spec_text(TABLE_EXTENSION_SPEC)
        plan = build_artifact_plan(spec)

        staging_dir = self.root / "graphify-staging-strong-catalog"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        graph_output_dir = self.root / "graphify-run-strong-catalog"
        run_graphify_staging(staging_dir, graph_output_dir, include_html=False)
        graph_index = GraphIndex(graph_output_dir / "graph.json")

        bundle = build_generation_bundle(
            spec, plan, catalog, self.repo_root, example_limit=3,
            graph_index=graph_index, graph_query="AifUserSessionService",
        )

        example_names = [ex["artifact"]["name"] for ex in bundle["examples"]]
        self.assertEqual(example_names[0], "AssetTable.BABAccountsPayable")

    def test_graph_materialized_content_wins_on_name_collision(self) -> None:
        from d365fo_agent.generator import build_generation_bundle
        from d365fo_agent.graphify_runner import run_graphify_staging

        if not _GRAPHIFY_AVAILABLE:
            self.skipTest("graphify engine not installed (optional dependency)")
        from d365fo_agent.graph_query import GraphIndex
        from d365fo_agent.indexer import build_catalog
        from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify
        from d365fo_agent.rules import load_rules
        from d365fo_agent.specs import build_artifact_plan, parse_spec_text

        collision_dir = self.repo_root / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxService"
        collision_dir.mkdir(parents=True, exist_ok=True)
        collision_file = collision_dir / "AifUserSessionService.xml"
        collision_file.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<AxService xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
            '  <Name>AifUserSessionService</Name>\n'
            '  <Class>CatalogStubClass</Class>\n'
            '</AxService>\n',
            encoding="utf-8",
        )

        catalog = build_catalog(self.repo_root, load_rules(self.rules_path))
        spec = parse_spec_text(SERVICE_SPEC)
        plan = build_artifact_plan(spec)

        staging_dir = self.root / "graphify-staging-collision"
        export_packageslocal_to_graphify(self.packages_root, staging_dir)
        graph_output_dir = self.root / "graphify-run-collision"
        run_graphify_staging(staging_dir, graph_output_dir, include_html=False)
        graph_index = GraphIndex(graph_output_dir / "graph.json")

        bundle = build_generation_bundle(
            spec, plan, catalog, self.repo_root, example_limit=3,
            graph_index=graph_index, graph_query="UserSessionService",
        )

        collision_examples = [
            ex for ex in bundle["examples"]
            if ex["artifact"]["name"] == "AifUserSessionService"
        ]
        self.assertEqual(len(collision_examples), 1)
        self.assertEqual(collision_examples[0].get("source"), "graph")
        self.assertNotIn("CatalogStubClass", collision_examples[0]["content"])

    def test_table_field_type_recognizes_recid_suffix_as_int64(self) -> None:
        from d365fo_agent.generator import _table_field_type_for_edt

        self.assertEqual(_table_field_type_for_edt("BABBFCAccountRecId"), "AxTableFieldInt64")
        self.assertEqual(_table_field_type_for_edt("RefRecId"), "AxTableFieldInt64")
        self.assertEqual(_table_field_type_for_edt("Int64"), "AxTableFieldInt64")
        self.assertEqual(_table_field_type_for_edt("NoYesId"), "AxTableFieldEnum")
        self.assertEqual(_table_field_type_for_edt("RandomString"), "AxTableFieldString")

    def test_resolve_edt_field_type_reads_subtype_from_xml(self) -> None:
        # Standard layout: every EDT sits in a generic 'AxEdt' folder with the real subtype only in
        # the root's i:type attribute — so the resolver must READ the file, not trust the folder.
        from d365fo_agent import knowledge
        from d365fo_agent.index_store import D365Index

        edt_dir = self.root / "edtpkgs" / "EdtPkg" / "EdtPkg" / "AxEdt"
        edt_dir.mkdir(parents=True)
        (edt_dir / "MyAmount.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<AxEdt xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="" i:type="AxEdtReal">\n'
            "\t<Name>MyAmount</Name>\n\t<Extends>Amount</Extends>\n</AxEdt>\n",
            encoding="utf-8",
        )
        roots = [self.root / "edtpkgs"]
        with D365Index(self.root / "edt.db") as index:
            index.index_packages_local(self.root / "edtpkgs")
            self.assertEqual(knowledge.resolve_edt_field_type(index, "MyAmount", roots), "AxTableFieldReal")
            self.assertIsNone(knowledge.resolve_edt_field_type(index, "AbsentEdt", roots))

    def test_table_field_type_uses_resolver_then_heuristic(self) -> None:
        from d365fo_agent.generator import _table_field_type_for_edt

        resolver = {"MyAmount": "AxTableFieldReal"}.get  # dict.get is a str->str|None resolver
        self.assertEqual(_table_field_type_for_edt("MyAmount", resolver), "AxTableFieldReal")
        # resolver returns None -> heuristic fallback still applies
        self.assertEqual(_table_field_type_for_edt("FooRecId", resolver), "AxTableFieldInt64")
        self.assertEqual(_table_field_type_for_edt("FreeText", resolver), "AxTableFieldString")

    def test_table_extension_merges_into_existing_alternative_when_name_omitted(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        existing_dir = self.repo_root / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxTableExtension"
        existing_dir.mkdir(parents=True, exist_ok=True)
        existing_path = existing_dir / "MainAccount.InterfaceLegacy.xml"
        existing_path.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
            '\t<Name>MainAccount.InterfaceLegacy</Name>\n'
            '\t<Fields />\n'
            '\t<Relations />\n'
            '</AxTableExtension>\n',
            encoding="utf-8",
        )

        spec_text = """# Extend main account with RecId link

Artifact Family: table-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: MainAccount

## Fields
- BABCustomLinkRecId: CustomLinkEdtRecId
"""
        spec_path = self.root / "table-ext-alternative-merge.md"
        spec_path.write_text(spec_text, encoding="utf-8")
        output_dir = self.root / "generated-alternative-merge"

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        self.assertEqual(result["artifact_results"][0]["generation_mode"], "merged")
        redirected_file = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxTableExtension" / "MainAccount.InterfaceLegacy.xml"
        self.assertTrue(redirected_file.exists())
        merged_xml = redirected_file.read_text(encoding="utf-8")
        self.assertIn("<Name>MainAccount.InterfaceLegacy</Name>", merged_xml)
        self.assertIn("<Name>BABCustomLinkRecId</Name>", merged_xml)
        self.assertIn('i:type="AxTableFieldInt64"', merged_xml)

    def test_table_extension_does_not_redirect_when_multiple_alternatives_exist(self) -> None:
        from d365fo_agent.generator import generate_from_spec_file

        existing_dir = self.repo_root / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxTableExtension"
        existing_dir.mkdir(parents=True, exist_ok=True)
        (existing_dir / "CustTable.InterfaceA.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
            '\t<Name>CustTable.InterfaceA</Name>\n'
            '\t<Fields />\n'
            '</AxTableExtension>\n',
            encoding="utf-8",
        )
        (existing_dir / "CustTable.InterfaceB.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
            '\t<Name>CustTable.InterfaceB</Name>\n'
            '\t<Fields />\n'
            '</AxTableExtension>\n',
            encoding="utf-8",
        )

        spec_text = """# Extend CustTable with a flag

Artifact Family: table-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: CustTable

## Fields
- BABFlag: NoYesId
"""
        spec_path = self.root / "table-ext-multi-alternative.md"
        spec_path.write_text(spec_text, encoding="utf-8")
        output_dir = self.root / "generated-multi-alternative"

        result = generate_from_spec_file(spec_path, self.repo_root, self.rules_path, output_dir)

        self.assertEqual(result["artifact_results"][0]["generation_mode"], "created")
        created_file = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxTableExtension" / "CustTable.BABAccountsPayable.xml"
        self.assertTrue(created_file.exists())

    def test_generate_from_spec_cli_writes_class_extension_xml(self) -> None:
        from d365fo_agent.cli import main

        spec_path = self.root / "class-extension.md"
        output_dir = self.root / "generated-class"
        spec_path.write_text(CLASS_EXTENSION_SPEC, encoding="utf-8")

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "generate-from-spec",
                    "--repo-root",
                    str(self.repo_root),
                    "--rules",
                    str(self.rules_path),
                    "--spec",
                    str(spec_path),
                    "--output-dir",
                    str(output_dir),
                ]
            )

        payload = json.loads(output.getvalue())
        generated_file = output_dir / "src" / "xplusplus" / "models" / "BABAccountsPayable" / "BABAccountsPayable" / "AxClass" / "BABAssetTable_Extension.xml"

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["artifact_plan"]["family"], "class-extension")
        self.assertTrue(generated_file.exists())
        xml = generated_file.read_text(encoding="utf-8")
        self.assertIn("[ExtensionOf(tableStr(AssetTable))]", xml)
        self.assertIn("public void delete()", xml)


class NewFamilyGenerationTests(unittest.TestCase):
    """Deterministic spec->XML generation for enum / enum-extension / EDT / data-entity-view-extension
    / view. Each rendered artifact must carry the right root and validate clean."""

    def _render(self, spec_text: str):
        from d365fo_agent.generator import render_artifact
        from d365fo_agent.specs import build_artifact_plans, parse_spec_text
        from d365fo_agent.validate import validate_xml

        plan = build_artifact_plans(parse_spec_text(spec_text))[0]
        xml = render_artifact(plan)
        report = validate_xml(xml, plan.family)
        return plan, xml, report

    def test_enum(self) -> None:
        plan, xml, report = self._render(
            "# Invoice status\nArtifact Family: enum\nModel: BABAccountsReceivable\n"
            "Artifact Name: BABInvoiceStatus\nLabel: @BAB:InvoiceStatus\n\n## Values\n- Due: @BAB:Due\n- NotDue: @BAB:NotDue\n"
        )
        self.assertEqual(plan.artifact_type, "AxEnum")
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn("<Name>BABInvoiceStatus</Name>", xml)
        self.assertIn("<Name>Due</Name>", xml)
        self.assertIn("<Value>1</Value>", xml)  # second value gets index 1
        self.assertIn("<IsExtensible>true</IsExtensible>", xml)

    def test_enum_extension(self) -> None:
        plan, xml, report = self._render(
            "# Extend posting type\nArtifact Family: enum-extension\nModel: BABGeneralLedger\n"
            "Target Object: LedgerPostingType\n\n## Values\n- BABTaxReInvoicing: @BAB:TaxReInvoicing\n"
        )
        self.assertEqual(plan.artifact_name, "LedgerPostingType.BABGeneralLedger")
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn("<AxEnumExtension", xml)
        self.assertIn("<Name>BABTaxReInvoicing</Name>", xml)
        self.assertIn("<ValueModifications />", xml)

    def test_edt_string(self) -> None:
        plan, xml, report = self._render(
            "# Account name EDT\nArtifact Family: edt\nModel: BAB-ExportBFC\nArtifact Name: BABBFCAccountName\n"
            "EDT Type: String\nString Size: 100\nLabel: @BAB:AccountName\n"
        )
        self.assertEqual(plan.artifact_type, "AxEdt")
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn('i:type="AxEdtString"', xml)
        self.assertIn("<StringSize>100</StringSize>", xml)
        self.assertIn("<Label>@BAB:AccountName</Label>", xml)

    def test_data_entity_view_extension(self) -> None:
        plan, xml, report = self._render(
            "# Extend bank account entity\nArtifact Family: data-entity-view-extension\nModel: BABGeneralLedger\n"
            "Target Object: BankAccountEntity\n\n## Fields\n- BABSwiftId: BankAccountTable.BABSwiftId\n"
        )
        self.assertEqual(plan.artifact_name, "BankAccountEntity.BABGeneralLedger")
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn('i:type="AxDataEntityViewMappedField"', xml)
        self.assertIn("<DataField>BABSwiftId</DataField>", xml)
        self.assertIn("<DataSource>BankAccountTable</DataSource>", xml)

    def test_view(self) -> None:
        plan, xml, report = self._render(
            "# Company view\nArtifact Family: view\nModel: BABVendorAgingBalance\nArtifact Name: BABCompanyView\n"
            "Root Table: CompanyInfo\nRoot Data Source: CompanyInfo\n\n## Fields\n- DataArea: CompanyInfo.DataArea\n"
        )
        self.assertEqual(plan.artifact_type, "AxView")
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn('i:type="AxViewFieldBound"', xml)
        self.assertIn("<AxQuerySimpleRootDataSource>", xml)
        self.assertIn("<Table>CompanyInfo</Table>", xml)

    def test_standalone_class(self) -> None:
        plan, xml, report = self._render(
            "# Bank trans calculator\nArtifact Family: class\nModel: BABGeneralLedger\n"
            "Artifact Name: BABBankTransCalculator\nExtends: RunBaseBatch\n\n"
            "## Methods\n- run(): public void\n- calculate(Amount _amt): protected Amount\n"
            "- exist(RefRecId _id): public static boolean\n"
        )
        self.assertEqual(plan.artifact_type, "AxClass")
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn("public class BABBankTransCalculator extends RunBaseBatch", xml)
        self.assertIn("<Name>run</Name>", xml)
        self.assertIn("<Name>calculate</Name>", xml)
        self.assertIn("public static boolean exist(RefRecId _id)", xml)  # qualifiers preserved
        self.assertIn("boolean _ret;", xml)  # compilable typed-return stub

    def test_standalone_table(self) -> None:
        plan, xml, report = self._render(
            "# Bank trans code table\nArtifact Family: table\nModel: BABGeneralLedger\n"
            "Artifact Name: BABBankTransCodeTbl\nLabel: @BAB:Code\n\n"
            "## Fields\n- BankCode: BankStatementIdentificationText\n- Descr: Description\n"
        )
        self.assertEqual(plan.artifact_type, "AxTable")
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn("<Name>BankCode</Name>", xml)
        self.assertIn("<AxTableFieldGroup>", xml)  # standard auto field groups
        self.assertIn("<Label>@BAB:Code</Label>", xml)
        self.assertIn("<StateMachines />", xml)

    def test_minimal_form(self) -> None:
        plan, xml, report = self._render(
            "# Flow origin form\nArtifact Family: form\nModel: BABGeneralLedger\n"
            "Artifact Name: BABFlowOriginForm\nRoot Table: BABFlowOriginTable\nRoot Data Source: FlowOriginTable\n"
            "Label: @BAB:Caption\n\n## Fields\n- FlowOriginId: FlowOriginId\n- Description: Description\n"
        )
        self.assertEqual(plan.artifact_type, "AxForm")
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn("<Table>BABFlowOriginTable</Table>", xml)
        self.assertIn('i:type="AxFormGridControl"', xml)
        self.assertIn("<Name>Grid_FlowOriginId</Name>", xml)
        self.assertIn("<Pattern xmlns=\"\">SimpleList</Pattern>", xml)

    def test_table_enum_field_uses_enumtype(self) -> None:
        from d365fo_agent.generator import _render_table_field

        def resolver(edt):  # base field-type resolver (unused here)
            return None

        resolver.enum_name = lambda e: e if e == "NoYes" else None  # NoYes is a base enum
        enum_field = _render_table_field({"name": "Status", "extended_data_type": "NoYes"}, resolver)
        self.assertIn('i:type="AxTableFieldEnum"', enum_field)
        self.assertIn("<EnumType>NoYes</EnumType>", enum_field)
        self.assertNotIn("<ExtendedDataType>", enum_field)
        # a non-enum field keeps ExtendedDataType
        edt_field = _render_table_field({"name": "Note", "extended_data_type": "Description"}, resolver)
        self.assertIn("<ExtendedDataType>Description</ExtendedDataType>", edt_field)
        self.assertNotIn("<EnumType>", edt_field)
