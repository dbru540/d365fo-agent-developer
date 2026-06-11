"""Tests for wiring a privilege into the security model (duty/role extension or new custom)."""

import unittest
from xml.etree import ElementTree as ET


class BuilderTests(unittest.TestCase):
    def test_duty_extension_shape(self):
        from d365fo_agent.security_wiring import build_duty_extension

        art = build_duty_extension("DataManagementOperationsMaintain", ["BABFooEntityMaintain"], suffix="BABFoo")
        self.assertEqual(art["name"], "DataManagementOperationsMaintain.BABFoo")
        self.assertEqual(art["family"], "security-duty-extension")
        root = ET.fromstring(art["xml"])  # well-formed
        self.assertEqual(root.tag.rsplit("}", 1)[-1], "AxSecurityDutyExtension")
        self.assertIn("<Name>BABFooEntityMaintain</Name>", art["xml"])
        self.assertIn("<PropertyModifications />", art["xml"])

    def test_duty_extension_requires_a_privilege(self):
        from d365fo_agent.security_wiring import build_duty_extension

        with self.assertRaises(ValueError):
            build_duty_extension("SomeDuty", [], suffix="BABFoo")

    def test_role_extension_with_duty_and_empty_privileges_self_closes(self):
        from d365fo_agent.security_wiring import build_role_extension

        art = build_role_extension("VendInvoiceAccountsPayableManager", suffix="BABFoo", duties=["BABFooDuty"])
        self.assertEqual(art["name"], "VendInvoiceAccountsPayableManager.BABFoo")
        self.assertIn("<Privileges />", art["xml"])  # empty -> self-closed, matches corpus
        self.assertIn("<AxSecurityDutyReference>", art["xml"])
        ET.fromstring(art["xml"])

    def test_role_extension_requires_duty_or_privilege(self):
        from d365fo_agent.security_wiring import build_role_extension

        with self.assertRaises(ValueError):
            build_role_extension("SomeRole", suffix="BABFoo")

    def test_new_custom_duty(self):
        from d365fo_agent.security_wiring import build_duty

        art = build_duty("BABCustomerExportMaintain", ["BABCustomerExportEntityPrivilege"], label="@BAB:Foo")
        self.assertEqual(art["family"], "security-duty")
        root = ET.fromstring(art["xml"])
        self.assertEqual(root.tag.rsplit("}", 1)[-1], "AxSecurityDuty")
        self.assertIn("<Label>@BAB:Foo</Label>", art["xml"])

    def test_new_custom_role(self):
        from d365fo_agent.security_wiring import build_role

        art = build_role("BABCustomerExportRole", duties=["BABCustomerExportMaintain"],
                         label="@BAB:Role", description="@BAB:Desc")
        root = ET.fromstring(art["xml"])
        self.assertEqual(root.tag.rsplit("}", 1)[-1], "AxSecurityRole")
        self.assertIn("<SubRoles />", art["xml"])
        self.assertIn("<AxSecurityDutyReference>", art["xml"])


class WireSecurityTests(unittest.TestCase):
    def test_extend_both_chains_privilege_duty_role(self):
        from d365fo_agent.security_wiring import wire_security

        result = wire_security("BABFooEntityMaintain", duty="DataManagementOperationsMaintain",
                               role="VendInvoiceAccountsPayableManager", suffix="BABFoo")
        families = [a["family"] for a in result["artifacts"]]
        self.assertEqual(families, ["security-duty-extension", "security-role-extension"])
        # the role extension references the duty (not the privilege) when a duty is provided
        role_art = result["artifacts"][1]
        self.assertIn("<Name>DataManagementOperationsMaintain</Name>", role_art["xml"])
        self.assertIn("<Privileges />", role_art["xml"])
        self.assertIn("privilege:BABFooEntityMaintain", result["chain"])
        self.assertIn("->", result["chain"])

    def test_role_only_references_privilege_directly(self):
        from d365fo_agent.security_wiring import wire_security

        result = wire_security("BABFooEntityMaintain", role="VendInvoiceAccountsPayableManager", suffix="BABFoo")
        self.assertEqual(len(result["artifacts"]), 1)
        role_art = result["artifacts"][0]
        self.assertIn("<Name>BABFooEntityMaintain</Name>", role_art["xml"])  # privilege ref
        self.assertIn("<Duties />", role_art["xml"])  # no duty

    def test_create_mode_emits_new_duty_and_role(self):
        from d365fo_agent.security_wiring import wire_security

        result = wire_security("BABFooEntityMaintain", duty="BABFooMaintain", role="BABFooRole",
                               extend_duty=False, extend_role=False)
        families = [a["family"] for a in result["artifacts"]]
        self.assertEqual(families, ["security-duty", "security-role"])

    def test_needs_duty_or_role(self):
        from d365fo_agent.security_wiring import wire_security

        with self.assertRaises(ValueError):
            wire_security("BABFooEntityMaintain")


class WireSecurityValidationTests(unittest.TestCase):
    """Each generated artifact must pass offline validation and clean naming-prefix linting."""

    def test_all_artifacts_validate(self):
        from d365fo_agent.security_wiring import wire_security
        from d365fo_agent.validate import validate_xml

        for kwargs in (
            {"duty": "DataManagementOperationsMaintain", "role": "VendInvoiceAccountsPayableManager", "suffix": "BABFoo"},
            {"role": "VendInvoiceAccountsPayableManager", "suffix": "BABFoo"},
            {"duty": "BABFooMaintain", "role": "BABFooRole", "extend_duty": False, "extend_role": False},
        ):
            result = wire_security("BABFooEntityMaintain", **kwargs)
            for art in result["artifacts"]:
                report = validate_xml(art["xml"], art["family"])
                self.assertTrue(report["valid"], f"{art['name']} ({art['family']}): {report['errors']}")

    def test_prefixed_suffix_lints_clean_unprefixed_warns(self):
        from d365fo_agent.linter import lint_artifact
        from d365fo_agent.security_wiring import build_duty_extension

        good = build_duty_extension("DataManagementOperationsMaintain", ["BABFooEntityMaintain"], suffix="BABFoo")
        report = lint_artifact(good["xml"], good["family"])  # no index: extension-target rules skipped
        self.assertFalse(any(f["rule_id"] == "naming-prefix" for f in report["findings"]))

        bad = build_duty_extension("DataManagementOperationsMaintain", ["FooEntityMaintain"], suffix="Foo")
        report = lint_artifact(bad["xml"], bad["family"])
        self.assertTrue(any(f["rule_id"] == "naming-prefix" for f in report["findings"]))


if __name__ == "__main__":
    unittest.main()
