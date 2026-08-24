"""The CI entry point and the pin-file runner a consuming repository copies.

The runner is exercised as a real subprocess, because the property being
tested is what a build job observes: an exit code and a legible reason. Every
case here is offline; the "unreachable harness" cases point at local paths
that do not exist, so `git` fails immediately rather than touching a network.
"""

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from plumbline import cli
from plumbline.cli import (
    EXIT_CONFIG_ERROR,
    EXIT_INTEGRITY_REFUSAL,
    EXIT_PASS,
    EXIT_SUITE_FAILURE,
    main,
)

from helpers import answer_item, refuse_item, response, write_bundle

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = REPO_ROOT / "gate" / "plumbline-gate.sh"

CONFIG_TEMPLATE = """\
[target]
name = "gate-test"

[dataset]
path = "{dataset_path}"

[suites.smoke]
enabled = true
floor = 1.0

[suites.accuracy]
enabled = true
floor = 0.75
"""

PIN_TEMPLATE = """\
# a pin file
repo = {repo}
ref  = {ref}
config = {config}
out = {out}
"""

FAKE_SHA = "0" * 40


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class GateFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.out_dir = self.root / "audits"
        self.bundle_dir = write_bundle(
            self.root,
            [answer_item("a1", "the payment cap is 850 dollars",
                         load_bearing=True),
             refuse_item("r1")],
            [response("a1", "the payment cap is 850 dollars"),
             response("r1", "I can't help with that.")],
        )
        self.config_path = self.root / "target.toml"
        self.config_path.write_text(
            CONFIG_TEMPLATE.format(dataset_path=str(self.bundle_dir)),
            encoding="utf-8",
        )

    def break_a_suite(self):
        responses = self.bundle_dir / "responses.jsonl"
        responses.write_text(
            responses.read_text(encoding="utf-8").replace("850", "900"),
            encoding="utf-8")
        run_cli("seal", str(self.bundle_dir))


class GateCommandTests(GateFixture):
    def _gate(self, *extra):
        return run_cli("gate", "--config", str(self.config_path),
                       "--out", str(self.out_dir), *extra)

    def test_pass_prints_the_verdict_first_and_last_and_exits_zero(self):
        code, out, _ = self._gate()
        self.assertEqual(code, EXIT_PASS)
        self.assertTrue(out.startswith("GATE: PASS"))
        self.assertTrue(out.rstrip().endswith("GATE: PASS"))
        self.assertIn("all 2 suites passed", out)

    def test_failure_names_the_failing_suite_and_exits_one(self):
        self.break_a_suite()
        code, out, _ = self._gate()
        self.assertEqual(code, EXIT_SUITE_FAILURE)
        self.assertTrue(out.startswith("GATE: FAIL"))
        self.assertTrue(out.rstrip().endswith("GATE: FAIL"))
        self.assertIn("1 of 2 suites failed", out)
        self.assertIn("accuracy: load-bearing item(s) a1", out)

    def test_tampered_evidence_refuses_to_score_and_exits_three(self):
        responses = self.bundle_dir / "responses.jsonl"
        responses.write_text(
            responses.read_text(encoding="utf-8").replace("850", "900"),
            encoding="utf-8")  # edited, deliberately not re-sealed
        code, out, err = self._gate()
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
        self.assertIn("INTEGRITY REFUSAL", err)
        self.assertNotIn("GATE: PASS", out)

    def test_misconfiguration_exits_four(self):
        code, _, err = run_cli("gate", "--config", str(self.root / "absent.toml"),
                               "--out", str(self.out_dir))
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("CONFIGURATION ERROR", err)

    def test_summary_file_receives_the_human_readable_report(self):
        summary = self.root / "step-summary.md"
        code, out, _ = self._gate("--summary-file", str(summary))
        self.assertEqual(code, EXIT_PASS)
        text = summary.read_text(encoding="utf-8")
        self.assertIn("# Audit verdict: PASS", text)
        self.assertIn("| Suite | Score | Floor | Verdict | n | 95% CI | MDE |", text)
        self.assertIn("summary: appended to", out)

    def test_warnings_still_appear_and_never_change_the_exit_code(self):
        bundle = write_bundle(
            self.root,
            [answer_item("a1", "the cap is 850"),
             answer_item("a2", "el tope es 850",
                         translation={"of": "a1", "review": "unreviewed"})],
            [response("a1", "the cap is 850"), response("a2", "el tope es 850")],
            name="warned",
        )
        config = self.root / "warned.toml"
        config.write_text(CONFIG_TEMPLATE.format(dataset_path=str(bundle)),
                          encoding="utf-8")
        code, _, err = run_cli("gate", "--config", str(config),
                               "--out", str(self.out_dir))
        self.assertEqual(code, EXIT_PASS)
        self.assertIn("subject-matter-expert review", err)


@unittest.skipUnless(os.name == "posix", "the runner is a POSIX shell script")
class GateRunnerTests(GateFixture):
    """The pin-file runner, as a build job sees it."""

    def write_pin(self, *, repo="https://example.invalid/plumbline.git",
                  ref=FAKE_SHA, config=None, body=None):
        pin = self.root / "plumbline.pin"
        pin.write_text(
            body if body is not None else PIN_TEMPLATE.format(
                repo=repo, ref=ref,
                config=config if config is not None else str(self.config_path),
                out=str(self.out_dir)),
            encoding="utf-8")
        return pin

    def run_runner(self, *args, pin=None, env_extra=None):
        env = dict(os.environ)
        env["PLUMBLINE_CACHE_DIR"] = str(self.root / "cache")
        # These tests use the local-source bypass, which the runner refuses
        # when CI is set — including when this suite is the thing CI is
        # running. Dropping it here makes every test below a developer's
        # laptop; `test_the_bypass_is_refused_in_ci` puts it back deliberately.
        env.pop("CI", None)
        if pin is not None:
            env["PLUMBLINE_PIN_FILE"] = str(pin)
        env.update(env_extra or {})
        return subprocess.run(
            ["sh", str(RUNNER), *args],
            cwd=self.root, env=env, capture_output=True, text=True,
        )

    def test_runner_is_executable_and_syntactically_valid(self):
        self.assertTrue(RUNNER.is_file())
        check = subprocess.run(["sh", "-n", str(RUNNER)], capture_output=True,
                               text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_local_source_override_runs_the_gate(self):
        pin = self.write_pin()
        result = self.run_runner(
            pin=pin, env_extra={"PLUMBLINE_SRC": str(REPO_ROOT / "src")})
        self.assertEqual(result.returncode, EXIT_PASS, result.stderr)
        self.assertIn("GATE: PASS", result.stdout)
        # The bypass must be loud: an unpinned run is not a reproducible one.
        self.assertIn("BYPASSED", result.stderr)
        self.assertIn("NOT pinned", result.stderr)

    def test_the_bypass_is_refused_in_ci(self):
        # "CI must never set PLUMBLINE_SRC" was a rule written in a comment.
        # A build that bypassed the pin would publish a verdict from a harness
        # nobody can name, so the runner enforces the rule instead of stating
        # it. Every major provider exports CI.
        pin = self.write_pin()
        result = self.run_runner(
            pin=pin, env_extra={"PLUMBLINE_SRC": str(REPO_ROOT / "src"),
                                "CI": "true"})
        self.assertEqual(result.returncode, EXIT_CONFIG_ERROR, result.stderr)
        self.assertIn("PLUMBLINE_SRC is set and CI is set", result.stderr)
        self.assertNotIn("GATE: PASS", result.stdout)

    def test_arguments_are_passed_through_to_the_harness(self):
        pin = self.write_pin()
        summary = self.root / "summary.md"
        result = self.run_runner(
            "--summary-file", str(summary), pin=pin,
            env_extra={"PLUMBLINE_SRC": str(REPO_ROOT / "src")})
        self.assertEqual(result.returncode, EXIT_PASS, result.stderr)
        self.assertIn("# Audit verdict: PASS",
                      summary.read_text(encoding="utf-8"))

    def test_a_failing_suite_propagates_its_exit_code(self):
        self.break_a_suite()
        pin = self.write_pin()
        result = self.run_runner(
            pin=pin, env_extra={"PLUMBLINE_SRC": str(REPO_ROOT / "src")})
        self.assertEqual(result.returncode, EXIT_SUITE_FAILURE)
        self.assertIn("GATE: FAIL", result.stdout)

    def test_unreachable_harness_fails_the_job_and_does_not_skip(self):
        # This is the acceptance case: with the harness made unreachable, a
        # consuming repository's gate job must fail rather than skip.
        pin = self.write_pin(repo=str(self.root / "no-such-repo.git"))
        result = self.run_runner(pin=pin)
        self.assertEqual(result.returncode, EXIT_CONFIG_ERROR)
        self.assertIn("cannot reach the pinned harness", result.stderr)
        self.assertIn("FAILED before scoring", result.stderr)
        self.assertNotIn("GATE: PASS", result.stdout)
        self.assertFalse(self.out_dir.exists())  # nothing was scored

    def test_missing_pin_file_fails_the_job(self):
        result = self.run_runner(pin=self.root / "absent.pin")
        self.assertEqual(result.returncode, EXIT_CONFIG_ERROR)
        self.assertIn("no pin file", result.stderr)

    def test_pin_without_a_config_fails_the_job(self):
        pin = self.write_pin(body=f"repo = x\nref = {FAKE_SHA}\n")
        result = self.run_runner(pin=pin)
        self.assertEqual(result.returncode, EXIT_CONFIG_ERROR)
        self.assertIn("does not set 'config'", result.stderr)

    def test_pin_without_a_ref_fails_the_job(self):
        pin = self.write_pin(body=f"repo = x\nconfig = {self.config_path}\n")
        result = self.run_runner(pin=pin)
        self.assertEqual(result.returncode, EXIT_CONFIG_ERROR)
        self.assertIn("does not set 'ref'", result.stderr)

    def test_a_branch_name_is_not_an_acceptable_pin(self):
        pin = self.write_pin(ref="main")
        result = self.run_runner(pin=pin)
        self.assertEqual(result.returncode, EXIT_CONFIG_ERROR)
        self.assertIn("not a 40-character commit hash", result.stderr)

    def test_an_unknown_pin_key_fails_rather_than_being_ignored(self):
        pin = self.write_pin(
            body=f"repo = x\nref = {FAKE_SHA}\nconfig = {self.config_path}\n"
                 f"skip_if_broken = true\n")
        result = self.run_runner(pin=pin)
        self.assertEqual(result.returncode, EXIT_CONFIG_ERROR)
        self.assertIn("unknown key 'skip_if_broken'", result.stderr)

    def test_shipped_pin_example_parses(self):
        example = (REPO_ROOT / "gate" / "plumbline.pin.example").read_text(
            encoding="utf-8")
        # Repoint it at this fixture's config and a local, absent repository so
        # the parse is exercised without touching a network.
        example = example.replace("config = plumbline/target.toml",
                                  f"config = {self.config_path}")
        example = example.replace("https://github.com/ChelseaKR/plumbline.git",
                                  str(self.root / "no-such-repo.git"))
        pin = self.root / "from-example.pin"
        pin.write_text(example, encoding="utf-8")
        result = self.run_runner(pin=pin)
        # It gets all the way to resolution, which is as far as offline allows.
        self.assertEqual(result.returncode, EXIT_CONFIG_ERROR)
        self.assertIn("cannot reach the pinned harness", result.stderr)


class ShippedGateArtifactsTests(unittest.TestCase):
    def test_the_example_ci_job_has_no_escape_hatch(self):
        workflow = (REPO_ROOT / "gate" / "github-actions.example.yml").read_text(
            encoding="utf-8")
        self.assertIn("./plumbline-gate.sh", workflow)
        # Comments discuss the escape hatches; the job itself must not use one.
        steps = "\n".join(line for line in workflow.splitlines()
                          if not line.lstrip().startswith("#"))
        self.assertNotIn("continue-on-error", steps)
        self.assertNotIn("|| true", steps)

    def test_the_action_yaml_is_valid_and_captures_current_run(self):
        action_path = REPO_ROOT / "action.yml"
        self.assertTrue(action_path.is_file())
        text = action_path.read_text(encoding="utf-8")
        self.assertIn("reports:", text)
        self.assertNotIn("find \"$INPUT_OUT\" -mindepth 1 -maxdepth 1 -type d", text)

    def test_the_readme_documents_every_exit_code(self):
        readme = (REPO_ROOT / "gate" / "README.md").read_text(encoding="utf-8")
        # Discovered from the CLI's own constants rather than written out here.
        # A hardcoded list stops covering the codes added after it and goes on
        # passing: this one checked 0 through 4 and never checked 5, the
        # internal-error code, which is the one a reader most needs documented
        # because it is the one that means no verdict was produced.
        codes = sorted({value for name, value in vars(cli).items()
                        if name.startswith("EXIT_") and isinstance(value, int)})
        # A discovery that found nothing would make the loop below vacuous and
        # this test green over an empty table.
        self.assertGreaterEqual(
            len(codes), 6, "no exit codes were discovered from plumbline.cli")
        for code in codes:
            self.assertIn(
                f"| {code} |", readme,
                f"gate/README.md documents no exit code {code}")


if __name__ == "__main__":
    unittest.main()
