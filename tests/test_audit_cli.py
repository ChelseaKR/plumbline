"""End-to-end tests through the CLI entry point: exit codes, provenance,
byte-reproducibility, and the milestone-1 half of the tamper drill."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from plumbline.cli import (
    EXIT_CONFIG_ERROR,
    EXIT_INTEGRITY_REFUSAL,
    EXIT_PASS,
    EXIT_SUITE_FAILURE,
    main,
)

from helpers import (
    answer_item,
    refuse_item,
    response,
    temporary_skeleton_suite,
    write_bundle,
)

CONFIG_TEMPLATE = """\
[target]
name = "cli-test"

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
"""


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.out_dir = self.root / "audits"
        self.bundle_dir = write_bundle(
            self.root,
            [
                answer_item("a1", "the payment cap is 850 dollars",
                            load_bearing=True),
                answer_item("a2", "offices open monday through friday",
                            translation={"of": "a1", "review": "unreviewed"}),
                refuse_item("r1"),
            ],
            [
                response("a1", "the payment cap is 850 dollars"),
                response("a2", "offices open monday through friday"),
                response("r1", "I can't help with that."),
            ],
        )
        self.config_path = self.root / "target.toml"
        self.config_path.write_text(
            CONFIG_TEMPLATE.format(dataset_path=str(self.bundle_dir)),
            encoding="utf-8",
        )

    def _audit(self):
        return run_cli("audit", "--config", str(self.config_path),
                       "--out", str(self.out_dir))

    def _report_paths(self):
        run_dirs = sorted(self.out_dir.iterdir())
        self.assertEqual(len(run_dirs), 1)
        return run_dirs[0] / "report.json", run_dirs[0] / "report.md"

    def test_pass_run_exit_zero_with_full_provenance(self):
        code, out, err = self._audit()
        self.assertEqual(code, EXIT_PASS)
        self.assertIn("verdict: PASS", out)
        json_path, md_path = self._report_paths()
        report = json.loads(json_path.read_text(encoding="utf-8"))
        # Overall verdict first.
        self.assertEqual(next(iter(report)), "verdict")
        prov = report["provenance"]
        for field in ("run_id", "harness_version", "seed",
                      "dataset_sha256", "judge_config_sha256"):
            self.assertTrue(prov.get(field), f"missing provenance field {field}")
        self.assertTrue(
            md_path.read_text(encoding="utf-8").startswith("# Audit verdict: PASS")
        )

    def test_every_suite_reports_score_floor_verdict_ci_and_mde(self):
        self._audit()
        json_path, md_path = self._report_paths()
        report = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertTrue(report["suites"])
        for suite in report["suites"]:
            for field in ("score", "floor", "verdict", "n", "stats"):
                self.assertIn(field, suite)
            self.assertIsNotNone(suite["ci"], f"{suite['suite']} has no CI")
            self.assertIsNotNone(suite["mde"], f"{suite['suite']} has no MDE")
            self.assertLessEqual(suite["ci"]["lower"], suite["score"] + 1e-9)
            self.assertGreaterEqual(suite["ci"]["upper"], suite["score"] - 1e-9)
        markdown = md_path.read_text(encoding="utf-8")
        self.assertIn("| Suite | Score | Floor | Verdict | n | 95% CI | MDE |",
                      markdown)
        self.assertIn("smallest true drop", markdown)

    def test_reports_byte_identical_across_reruns(self):
        self._audit()
        json_path, md_path = self._report_paths()
        first = (json_path.read_bytes(), md_path.read_bytes())
        self._audit()
        self.assertEqual((json_path.read_bytes(), md_path.read_bytes()), first)

    def test_unreviewed_warning_on_every_run_never_fatal(self):
        for _ in range(2):
            code, _, err = self._audit()
            self.assertEqual(code, EXIT_PASS)
            self.assertIn("WARNING", err)
            self.assertIn("subject-matter-expert review", err)

    def test_tamper_refusal_then_reseal_fail(self):
        # Milestone-1 half of the spec's tamper drill.
        responses_path = self.bundle_dir / "responses.jsonl"
        responses_path.write_text(
            responses_path.read_text(encoding="utf-8").replace("850", "900"),
            encoding="utf-8",
        )
        # First run: integrity refusal, nothing scored, distinct exit code.
        code, out, err = self._audit()
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
        self.assertIn("INTEGRITY REFUSAL", err)
        self.assertNotIn("verdict", out)
        self.assertFalse(self.out_dir.exists())  # no report written

        # Legitimate regeneration: reseal, then the planted number fails
        # the load-bearing accuracy check -> overall FAIL, exit 1.
        code, _, _ = run_cli("seal", str(self.bundle_dir))
        self.assertEqual(code, EXIT_PASS)
        code, out, _ = self._audit()
        self.assertEqual(code, EXIT_SUITE_FAILURE)
        self.assertIn("verdict: FAIL", out)
        json_path, _ = self._report_paths()
        report = json.loads(json_path.read_text(encoding="utf-8"))
        accuracy = next(s for s in report["suites"] if s["suite"] == "accuracy")
        self.assertEqual(accuracy["verdict"], "FAIL")
        self.assertEqual(accuracy["details"]["load_bearing_failures"], ["a1"])

    def test_missing_checksums_is_integrity_refusal(self):
        (self.bundle_dir / "checksums.json").unlink()
        code, _, err = self._audit()
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
        self.assertIn("INTEGRITY REFUSAL", err)

    def test_enabling_unimplemented_suite_is_config_error(self):
        with temporary_skeleton_suite() as suite_id:
            self.config_path.write_text(
                self.config_path.read_text(encoding="utf-8")
                + f"\n[suites.{suite_id}]\nenabled = true\n",
                encoding="utf-8",
            )
            code, _, err = self._audit()
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("skeleton", err)

    def test_suite_with_nothing_to_score_is_config_error_not_a_pass(self):
        # The fixture bundle has no fact asked in two languages, so the
        # cross-language suite has an empty population. Fail closed.
        self.config_path.write_text(
            self.config_path.read_text(encoding="utf-8")
            + "\n[suites.cross_language]\nenabled = true\n",
            encoding="utf-8",
        )
        code, out, err = self._audit()
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("nothing for it to score", err)
        self.assertNotIn("verdict", out)

    def test_unknown_suite_is_config_error(self):
        self.config_path.write_text(
            self.config_path.read_text(encoding="utf-8")
            + "\n[suites.vibes]\nenabled = true\n",
            encoding="utf-8",
        )
        code, _, err = self._audit()
        self.assertEqual(code, EXIT_CONFIG_ERROR)

    def test_no_enabled_suites_is_config_error(self):
        self.config_path.write_text(
            CONFIG_TEMPLATE.format(dataset_path=str(self.bundle_dir))
            .replace("enabled = true", "enabled = false"),
            encoding="utf-8",
        )
        code, _, err = self._audit()
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("vacuous", err)

    def test_validate_reports_count_and_short_hash(self):
        code, out, err = run_cli("validate", str(self.bundle_dir))
        self.assertEqual(code, EXIT_PASS)
        self.assertIn("items:    3", out)
        self.assertIn("dataset:", out)
        self.assertIn("WARNING", err)


if __name__ == "__main__":
    unittest.main()
