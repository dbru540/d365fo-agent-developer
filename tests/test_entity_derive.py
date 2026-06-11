"""Tests for deriving a public OData entity (+privilege) from a standard one."""

import unittest
from xml.etree import ElementTree as ET

SOURCE_ENTITY = """<?xml version="1.0" encoding="utf-8"?>
<AxDataEntityView xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>StdCustomerEntity</Name>
\t<SourceCode>
\t\t<Declaration><![CDATA[
public class StdCustomerEntity extends common
{
}
]]></Declaration>
\t\t<Methods />
\t</SourceCode>
\t<Label>@SYS:StandardCustomer</Label>
\t<DataManagementEnabled>No</DataManagementEnabled>
\t<IsPublic>No</IsPublic>
\t<PublicCollectionName>StdCustomers</PublicCollectionName>
\t<PublicEntityName>StdCustomer</PublicEntityName>
\t<Fields>
\t\t<AxDataEntityViewField><Name>AccountNum</Name></AxDataEntityViewField>
\t\t<AxDataEntityViewField><Name>Name</Name></AxDataEntityViewField>
\t</Fields>
\t<Keys><Key><Name>EntityKey</Name></Key></Keys>
</AxDataEntityView>
"""


class DeriveEntityTests(unittest.TestCase):
    def derive(self, **kw):
        from d365fo_agent.entity_derive import derive_public_entity

        return derive_public_entity(SOURCE_ENTITY, kw.pop("new_name", "BABCustomerExportEntity"), **kw)

    def test_sets_public_and_names(self):
        result = self.derive(public_entity_name="BABCustomerExport", public_collection_name="BABCustomerExports")
        root = ET.fromstring(result["xml"])
        text = {c.tag.rsplit("}", 1)[-1]: c.text for c in root if c.text}
        self.assertEqual(text["Name"], "BABCustomerExportEntity")
        self.assertEqual(text["IsPublic"], "Yes")
        self.assertEqual(text["PublicEntityName"], "BABCustomerExport")
        self.assertEqual(text["PublicCollectionName"], "BABCustomerExports")

    def test_default_public_names_derived_from_new_name(self):
        result = self.derive()
        self.assertEqual(result["public_entity_name"], "BABCustomerExport")  # "Entity" suffix stripped
        self.assertEqual(result["public_collection_name"], "BABCustomerExports")

    def test_preserves_fields(self):
        result = self.derive()
        self.assertEqual(result["field_count"], 2)
        self.assertIn("<Name>AccountNum</Name>", result["xml"])
        self.assertIn("<Name>Name</Name>", result["xml"])

    def test_renames_declaration_class(self):
        result = self.derive()
        self.assertIn("class BABCustomerExportEntity extends common", result["xml"])
        self.assertNotIn("class StdCustomerEntity extends", result["xml"])

    def test_relabel(self):
        result = self.derive(label="@BABAccountsPayable:CustomerExport")
        root = ET.fromstring(result["xml"])
        label = next(c.text for c in root if c.tag.rsplit("}", 1)[-1] == "Label")
        self.assertEqual(label, "@BABAccountsPayable:CustomerExport")

    def test_data_management_toggle(self):
        result = self.derive(data_management=True, staging_table="BABCustomerExportStaging")
        self.assertIn("<DataManagementEnabled>Yes</DataManagementEnabled>", result["xml"])
        self.assertIn("<DataManagementStagingTable>BABCustomerExportStaging</DataManagementStagingTable>", result["xml"])

    def test_source_untouched_when_data_management_none(self):
        result = self.derive()  # data_management defaults None -> keep source value
        self.assertIn("<DataManagementEnabled>No</DataManagementEnabled>", result["xml"])

    def test_derived_xml_is_well_formed(self):
        ET.fromstring(self.derive()["xml"])  # raises on malformed


class EntityPrivilegeTests(unittest.TestCase):
    def build(self, **kw):
        from d365fo_agent.entity_derive import build_entity_privilege

        return build_entity_privilege(kw.pop("entity", "BABCustomerExportEntity"), **kw)

    def test_default_full_crud_odata(self):
        result = self.build()
        self.assertEqual(result["grants"], ["Read", "Create", "Update", "Delete"])
        self.assertEqual(result["integration_mode"], "OData")
        self.assertIn("<AxSecurityDataEntityPermission>", result["xml"])
        self.assertIn("<Name>BABCustomerExportEntity</Name>", result["xml"])
        self.assertIn("<IntegrationMode>OData</IntegrationMode>", result["xml"])

    def test_read_only(self):
        result = self.build(grants=["Read"])
        self.assertIn("<Read>Allow</Read>", result["xml"])
        self.assertNotIn("<Delete>Allow</Delete>", result["xml"])

    def test_well_formed_and_named(self):
        result = self.build(privilege_name="BABCustomerExportMaintain", label="@BAB:x")
        root = ET.fromstring(result["xml"])
        self.assertEqual(root.tag.rsplit("}", 1)[-1], "AxSecurityPrivilege")
        self.assertEqual(result["name"], "BABCustomerExportMaintain")


if __name__ == "__main__":
    unittest.main()
