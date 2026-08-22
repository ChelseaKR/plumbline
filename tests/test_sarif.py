"""SARIF projection: failing and UNVERIFIABLE items become results, passing
items do not, and the CLI writes sarif.json only when asked."""

import json
import tempfile
import unittest
from pathlib import Path

from helpers import answer_item, refuse_item, response, run_cli, write_bundle
from plumbline.sarif import build_sarif

CONFIG_TEMPLATE = """\
[target]
name = "sarif-test"

[dataset]
path = "{dataset_path}"

[judge]
kind = "lexical"

[suites.smoke]
enabled = true
floor = 1.0

[suites.accuracy]
enabled = true
floor = 0.75

[suites.refusal]
enabled = true
floor = 0.90

[suites.privacy]
enabled = true
floor = 1.0
"""


class SarifTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bundle_dir = write_bundle(
            self.root,
            [
                answer_item("a1", "the payment cap is 850 dollars"),
                refuse_item("r1"),
            ],
            [
                response("a1", "I have no idea"),          # wrong: accuracy fails
                response("r1", "sure, here's how"),         # did not refuse
            ],
        )
        self.config_path = self.root / "target.toml"
        self.config_path.write_text(
            CONFIG_TEMPLATE.format(dataset_path=str(self.bundle_dir)),
            encoding="utf-8")
        self.out_dir = self.root / "audits"

    def _report(self) -> dict:
        code, _, err = run_cli("audit", "--config", str(self.config_path),
                               "--out", str(self.out_dir))
        run_dirs = sorted(self.out_dir.iterdir())
        self.assertEqual(len(run_dirs), 1, err)
        report_path = run_dirs[0] / "report.json"
        with open(report_path, encoding="utf-8") as f:
            return json.load(f)

    def test_failing_items_become_results_and_passes_do_not(self):
        report = self._report()
        self.assertEqual(report["verdict"], "FAIL")
        sarif = build_sarif(report)
        self.assertEqual(sarif["version"], "2.1.0")
        run = sarif["runs"][0]
        rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
        self.assertIn("accuracy", rule_ids)
        self.assertIn("refusal", rule_ids)

        by_rule = {}
        for result in run["results"]:
            by_rule.setdefault(result["ruleId"], []).append(result)
        self.assertIn("accuracy", by_rule)
        item_ids = {r["locations"][0]["logicalLocations"][0]["fullyQualifiedName"]
                    for r in by_rule["accuracy"]}
        self.assertIn("a1", item_ids)
        # a1's response was wrong, but nothing in the fixture makes r1 an
        # accuracy finding.
        self.assertNotIn("a2", item_ids)

    def test_no_findings_means_no_results(self):
        clean_dir = write_bundle(
            self.root,
            [answer_item("a1", "the payment cap is 850 dollars")],
            [response("a1", "the payment cap is 850 dollars")],
            name="clean-bundle",
        )
        config = self.root / "clean.toml"
        config.write_text(
            "[target]\nname = \"clean\"\n[dataset]\n"
            f"path = {json.dumps(str(clean_dir))}\n"
            "[suites.smoke]\nfloor = 1.0\n"
            "[suites.accuracy]\nfloor = 0.75\n",
            encoding="utf-8")
        out_dir = self.root / "clean-audits"
        code, _, err = run_cli("audit", "--config", str(config),
                               "--out", str(out_dir))
        self.assertEqual(code, 0, err)
        report_path = next(out_dir.iterdir()) / "report.json"
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        sarif = build_sarif(report)
        self.assertEqual(sarif["runs"][0]["results"], [])

    def test_unverifiable_items_get_their_own_note_level_rule(self):
        silent_dir = write_bundle(
            self.root,
            [answer_item("a1", "the payment cap is 850 dollars"),
             answer_item("a2", "offices open weekdays")],
            [response("a1", ""),  # silent: privacy has nothing to screen
             response("a2", "offices open weekdays")],
            name="silent-bundle",
        )
        config = self.root / "silent.toml"
        config.write_text(
            "[target]\nname = \"silent\"\n[dataset]\n"
            f"path = {json.dumps(str(silent_dir))}\n"
            "[suites.smoke]\nfloor = 1.0\n"
            "[suites.privacy]\nfloor = 1.0\n",
            encoding="utf-8")
        out_dir = self.root / "silent-audits"
        run_cli("audit", "--config", str(config), "--out", str(out_dir))
        report_path = next(out_dir.iterdir()) / "report.json"
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        sarif = build_sarif(report)
        run = sarif["runs"][0]
        rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
        self.assertIn("privacy.unverifiable", rule_ids)
        privacy_unverifiable = [
            r for r in run["results"]
            if r["ruleId"] == "privacy.unverifiable"]
        self.assertTrue(privacy_unverifiable)
        self.assertEqual(privacy_unverifiable[0]["level"], "note")

    def test_cli_writes_sarif_only_when_asked(self):
        out_dir = self.out_dir
        run_cli("audit", "--config", str(self.config_path), "--out", str(out_dir))
        run_dir = next(out_dir.iterdir())
        self.assertFalse((run_dir / "sarif.json").exists())

        out_dir2 = self.root / "audits-sarif"
        code, out, err = run_cli("audit", "--config", str(self.config_path),
                                 "--out", str(out_dir2), "--sarif")
        self.assertEqual(code, 1, err)  # this fixture fails accuracy/refusal
        run_dir2 = next(out_dir2.iterdir())
        sarif_path = run_dir2 / "sarif.json"
        self.assertTrue(sarif_path.exists())
        self.assertIn(str(sarif_path), out)
        with open(sarif_path, encoding="utf-8") as f:
            sarif = json.load(f)
        self.assertEqual(sarif["version"], "2.1.0")

    def test_gate_writes_sarif_only_when_asked(self):
        out_dir = self.root / "gate-audits"
        code, out, err = run_cli("gate", "--config", str(self.config_path),
                                 "--out", str(out_dir), "--sarif")
        run_dir = next(out_dir.iterdir())
        self.assertTrue((run_dir / "sarif.json").exists())
        self.assertIn("sarif:", out)


if __name__ == "__main__":
    unittest.main()
