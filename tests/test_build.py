import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from test_catalog import TEST_TEMP_ROOT

# Real xppc.exe logs captured from this corpus (one failing, one clean-with-warnings).
XPPC_LOG_FATAL = """==================================
ExternalReference Warning: dynamics://Reference/Microsoft.Dynamics.PricingEngine: Assembly 'Microsoft.Dynamics.Commerce.Runtime.Entities.AttributeBasedPricing, Version=7.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35' failed to load because it was not found.
Compile Fatal Error: Failed to write runtime metadata to disk. The exception was: 'Object reference not set to an instance of an object.'
==================================
Errors: 1
Warnings: 1
"""

XPPC_LOG_WARNINGS = """==================================
ExternalReference Warning: dynamics://Reference/Microsoft.Dynamics.PricingEngine: Assembly 'Microsoft.Dynamics.Commerce.Runtime.Entities.AttributeBasedPricing' failed to load because it was not found.
Compile Warning: Class Method dynamics://Class/BABSuspendDimensionPerLegalEntity/Method/run: [(223,9),(223,45)]: 'DimensionAttributeValueFinancialStmt' is obsolete.
==================================
Errors: 0
Warnings: 2
"""

# Real PackagesLocalDirectory on this dev box — present here, absent in CI / other machines.
_REAL_PLD = Path(__file__).resolve().parents[1] / "D365_repo" / "BabilouFinOps" / "PackagesLocalDirectory"
_XPPC_AVAILABLE = (_REAL_PLD / "bin" / "xppc.exe").exists()


MSBUILD_PROJECT = """<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003" ToolsVersion="14.0">
  <PropertyGroup>
    <MetadataDirectory>$(registry:HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Dynamics\\AX\\7.0\\SDK@MetadataPath)</MetadataDirectory>
    <DynamicsSDK>$(registry:HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Dynamics\\AX\\7.0\\SDK@DynamicsSDK)</DynamicsSDK>
  </PropertyGroup>
</Project>
"""


class BuildTests(unittest.TestCase):
    def test_build_runner_prepares_msbuild_command_without_executing(self) -> None:
        from d365fo_agent.build import BuildRunner

        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        temp_dir = TEST_TEMP_ROOT / str(uuid4())
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            project_path = temp_dir / "AXModulesBuild.proj"
            project_path.write_text(MSBUILD_PROJECT, encoding="utf-8")

            runner = BuildRunner(msbuild_executable="msbuild.exe")
            result = runner.build_project(project_path, execute=False, output_path=temp_dir / "out")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(result.command[0], "msbuild.exe")
        self.assertIn(str(project_path), result.command)
        self.assertTrue(any(arg.startswith("/p:OutputPath=") for arg in result.command))
        self.assertEqual(result.status, "planned")


class XppLogParseTests(unittest.TestCase):
    def test_parses_fatal_error_log(self) -> None:
        from d365fo_agent.build import parse_xppc_log

        parsed = parse_xppc_log(XPPC_LOG_FATAL)
        self.assertEqual(parsed["error_count"], 1)
        self.assertEqual(parsed["warning_count"], 1)
        fatal = [d for d in parsed["diagnostics"] if d.severity == "error"]
        self.assertEqual(len(fatal), 1)
        self.assertIn("Fatal", fatal[0].category)
        self.assertIn("runtime metadata", fatal[0].message)

    def test_parses_warning_with_element_and_location(self) -> None:
        from d365fo_agent.build import parse_xppc_log

        parsed = parse_xppc_log(XPPC_LOG_WARNINGS)
        self.assertEqual(parsed["error_count"], 0)
        self.assertEqual(parsed["warning_count"], 2)
        obsolete = [d for d in parsed["diagnostics"] if "obsolete" in d.message]
        self.assertEqual(len(obsolete), 1)
        self.assertEqual(obsolete[0].element, "dynamics://Class/BABSuspendDimensionPerLegalEntity/Method/run")
        self.assertEqual(obsolete[0].location, "(223,9),(223,45)")

    def test_counts_fall_back_to_diagnostics_when_summary_absent(self) -> None:
        from d365fo_agent.build import parse_xppc_log

        parsed = parse_xppc_log("Compile Error: dynamics://Class/X/Method/y: something broke.\n")
        self.assertEqual(parsed["error_count"], 1)


class XppCompilerTests(unittest.TestCase):
    def test_unavailable_when_xppc_missing(self) -> None:
        from d365fo_agent.build import XppCompiler

        compiler = XppCompiler(TEST_TEMP_ROOT / "no_such_pld")
        self.assertFalse(compiler.available())
        result = compiler.compile_model("AnyModel", output_path=TEST_TEMP_ROOT / "o", log_path=TEST_TEMP_ROOT / "c.log")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("Windows D365 host", result.message)

    @unittest.skipUnless(_XPPC_AVAILABLE, "xppc.exe not present (needs a Windows D365 host)")
    def test_real_compile_of_custom_model(self) -> None:
        from d365fo_agent.build import XppCompiler

        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        work = TEST_TEMP_ROOT / str(uuid4())
        work.mkdir(parents=True, exist_ok=True)
        try:
            compiler = XppCompiler(_REAL_PLD)
            result = compiler.compile_model(
                "BABSuspendDimensionPerLegalEntity",
                output_path=work / "out", log_path=work / "compile.log",
            )
            self.assertEqual(result.status, "succeeded", result.message)
            self.assertEqual(result.error_count, 0)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class CompileOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.pld = self.root / "PLD"
        (self.pld / "Pkg" / "Pkg" / "AxClass").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _fake_compiler(self, recorder: dict):
        from d365fo_agent.build import CompileResult, XppCompiler

        class _Fake(XppCompiler):
            def available(self_inner) -> bool:  # noqa: N805
                return True

            def compile_model(self_inner, model, *, output_path, log_path, **kw):  # noqa: N805
                recorder["during"] = {p.name: p.read_text(encoding="utf-8") for p in self_inner.packages_root.rglob("*.xml")}
                return CompileResult(status="succeeded", model=model, error_count=0)

        return _Fake(self.pld)

    def test_added_file_is_present_during_compile_then_removed(self) -> None:
        rec: dict = {}
        rel = "Pkg/Pkg/AxClass/Foo.xml"
        result = self._fake_compiler(rec).compile_overlay(
            "Pkg", [(rel, "<AxClass><Name>Foo</Name></AxClass>")],
            output_path=self.root / "o", log_path=self.root / "l.log",
        )
        self.assertEqual(result.status, "succeeded")
        self.assertIn("Foo.xml", rec["during"])  # overlaid during the compile
        self.assertFalse((self.pld / rel).exists())  # removed afterwards (was absent before)

    def test_overwritten_file_is_restored(self) -> None:
        rec: dict = {}
        rel = "Pkg/Pkg/AxClass/Bar.xml"
        (self.pld / rel).write_text("ORIGINAL", encoding="utf-8")
        self._fake_compiler(rec).compile_overlay(
            "Pkg", [(rel, "NEW")], output_path=self.root / "o", log_path=self.root / "l.log"
        )
        self.assertEqual(rec["during"]["Bar.xml"], "NEW")  # the new content was compiled
        self.assertEqual((self.pld / rel).read_text(encoding="utf-8"), "ORIGINAL")  # then restored

    def test_pld_restored_even_when_compile_raises(self) -> None:
        from d365fo_agent.build import XppCompiler

        rel = "Pkg/Pkg/AxClass/Boom.xml"

        class _Boom(XppCompiler):
            def available(self) -> bool:
                return True

            def compile_model(self, *a, **k):
                raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            _Boom(self.pld).compile_overlay("Pkg", [(rel, "X")], output_path=self.root / "o", log_path=self.root / "l.log")
        self.assertFalse((self.pld / rel).exists())  # restored despite the exception

    @unittest.skipUnless(_XPPC_AVAILABLE, "xppc.exe not present (needs a Windows D365 host)")
    def test_real_overlay_compile_and_restore(self) -> None:
        from d365fo_agent.build import XppCompiler

        model = "BABSuspendDimensionPerLegalEntity"
        rel = f"{model}/{model}/AxClass/BABOverlayProbe.xml"
        target = _REAL_PLD / rel
        self.assertFalse(target.exists())  # clean baseline
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        work = TEST_TEMP_ROOT / str(uuid4())
        work.mkdir(parents=True, exist_ok=True)
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<AxClass xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
            "\t<Name>BABOverlayProbe</Name>\n\t<SourceCode>\n"
            "\t\t<Declaration><![CDATA[\npublic class BABOverlayProbe\n{\n}\n]]></Declaration>\n"
            "\t\t<Methods />\n\t</SourceCode>\n</AxClass>\n"
        )
        meta = _REAL_PLD / model / "XppMetadata" / model / "AxClass" / "BABOverlayProbe.xml"
        try:
            result = XppCompiler(_REAL_PLD).compile_overlay(
                model, [(rel, xml)], output_path=work / "out", log_path=work / "compile.log"
            )
            self.assertEqual(result.status, "succeeded", result.message)
            self.assertEqual(result.error_count, 0)
            self.assertFalse(target.exists())  # source overlay restored by compile_overlay
            self.assertFalse(meta.exists())  # xppc's XppMetadata byproduct also restored
        finally:
            shutil.rmtree(work, ignore_errors=True)
            for leftover in (target, meta):  # belt-and-suspenders
                if leftover.exists():
                    leftover.unlink()
