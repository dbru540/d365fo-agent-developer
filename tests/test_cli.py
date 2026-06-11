import io
import json
import shutil
import unittest
from contextlib import redirect_stdout
from uuid import uuid4

from test_catalog import RULES_JSON, TEST_TEMP_ROOT, create_fixture_repo


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo_root = create_fixture_repo(self.root)
        self.rules_path = self.root / "rules.json"
        self.rules_path.write_text(json.dumps(RULES_JSON), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_inventory_command_outputs_summary_json(self) -> None:
        from d365fo_agent.cli import main

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "inventory",
                    "--repo-root",
                    str(self.repo_root),
                    "--rules",
                    str(self.rules_path),
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["model_count"], 1)
        self.assertEqual(payload["artifact_count"], 5)
        self.assertEqual(payload["classification_summary"]["custom-canonical"], 5)

    def test_find_element_command_returns_matching_artifact(self) -> None:
        from d365fo_agent.cli import main

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "find-element",
                    "--repo-root",
                    str(self.repo_root),
                    "--rules",
                    str(self.rules_path),
                    "--name",
                    "BABBFCAccount",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["matches"][0]["name"], "BABBFCAccount")
        self.assertEqual(payload["matches"][0]["artifact_type"], "AxSecurityPrivilege")
