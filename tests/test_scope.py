"""What a run says about the suites it did not run.

The suite table has always said which suites ran. Nothing said which ones
did not, so a `PASS` from a configuration that never enabled `privacy` was
indistinguishable, on its face, from a `PASS` that checked everything. These
tests are about the other half of that table.

The disclosure never changes a verdict, so "proving it can fail" here means
proving it cannot quietly go missing or quietly under-report: the count comes
from the registry rather than from a literal, and the block is inside the
sealed body of the report.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import answer_item, response, run_cli, write_bundle

from plumbline import scope
from plumbline.cli import EXIT_CONFIG_ERROR, EXIT_INTEGRITY_REFUSAL, EXIT_PASS
from plumbline.config import load_config
from plumbline.suites import available


class ScopeBlockTests(unittest.TestCase):
    def test_a_full_configuration_says_so_rather_than_saying_nothing(self):
        block = scope.analyze(scored=["smoke", "accuracy"], unscored={})
        self.assertEqual(block["not_scored"], [])
        self.assertEqual(block["implemented"], 2)
        self.assertIn("all 2 implemented suites were scored", block["summary"])

    def test_absent_and_disabled_are_reported_as_different_things(self):
        # They read differently in a review: one is usually a configuration
        # written before the suite existed, the other is a decision somebody
        # made and can be asked about.
        block = scope.analyze(
            scored=["smoke"],
            unscored={"privacy": scope.ABSENT, "refusal": scope.DISABLED})
        reasons = {e["suite"]: e["reason"] for e in block["not_scored"]}
        self.assertEqual(reasons, {"privacy": scope.ABSENT,
                                   "refusal": scope.DISABLED})
        self.assertIn("privacy (absent from the configuration)",
                      block["summary"])
        self.assertIn("refusal (enabled = false in the configuration)",
                      block["summary"])
        self.assertIn("reports nothing about what those suites check",
                      block["summary"])

    def test_the_denominator_counts_the_suites_that_did_not_run(self):
        block = scope.analyze(scored=["smoke"],
                              unscored={"privacy": scope.ABSENT})
        self.assertEqual((block["scored"], block["implemented"]), (1, 2))

    def test_the_markdown_names_every_unscored_suite(self):
        rendered = "\n".join(scope.render_markdown(scope.analyze(
            scored=["smoke"],
            unscored={"privacy": scope.ABSENT, "refusal": scope.DISABLED})))
        self.assertIn("## Scope", rendered)
        self.assertIn("`privacy`", rendered)
        self.assertIn("`refusal`", rendered)
        self.assertIn("1 of 3", rendered)

    def test_the_markdown_section_exists_even_when_nothing_is_missing(self):
        # A section that appears only on a partial configuration teaches a
        # reader to read its absence as a full one, which is the same mistake
        # in a different direction.
        rendered = "\n".join(scope.render_markdown(
            scope.analyze(scored=["smoke"], unscored={})))
        self.assertIn("## Scope", rendered)
        self.assertIn("All **1** implemented suites were scored", rendered)

    def test_the_terminal_line_names_them_too(self):
        lines = scope.summarize_for_terminal(scope.analyze(
            scored=["smoke"], unscored={"privacy": scope.ABSENT}))
        self.assertEqual(len(lines), 1)
        self.assertIn("NOT scored: privacy (absent)", lines[0])


class _Configured(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bundle = write_bundle(
            self.root, [answer_item("a1", "yes")], [response("a1", "yes")])

    def config(self, body: str, name: str = "target.toml") -> Path:
        path = self.root / name
        path.write_text(
            f'[target]\nname = "scope-test"\n[dataset]\n'
            f'path = {json.dumps(str(self.bundle))}\n{body}',
            encoding="utf-8")
        return path


class ConfigRecordsWhatItDoesNotHold(_Configured):
    def test_a_suite_the_configuration_never_mentions_is_absent(self):
        config = load_config(self.config(
            "[suites.smoke]\nenabled = true\nfloor = 1.0\n"))
        self.assertEqual(config.unscored.get("privacy"), scope.ABSENT)

    def test_a_suite_switched_off_is_disabled_not_absent(self):
        config = load_config(self.config(
            "[suites.smoke]\nenabled = true\nfloor = 1.0\n"
            "[suites.privacy]\nenabled = false\n"))
        self.assertEqual(config.unscored.get("privacy"), scope.DISABLED)

    def test_every_implemented_suite_is_accounted_for(self):
        # Registry-derived rather than written out: a suite added later is
        # counted here without anyone remembering to update a literal, which
        # is how a disclosure like this silently starts under-reporting.
        config = load_config(self.config(
            "[suites.smoke]\nenabled = true\nfloor = 1.0\n"))
        implemented = {s for s, cls in available().items() if cls.implemented}
        self.assertGreater(len(implemented), 1)
        self.assertEqual(set(config.suites) | set(config.unscored),
                         implemented)

    def test_a_disabled_suite_is_still_refused_if_it_does_not_exist(self):
        # Switching off a suite that was never real is a typo, not a policy.
        code, _, _ = run_cli(
            "audit", "--config",
            str(self.config("[suites.smoke]\nenabled = true\nfloor = 1.0\n"
                            "[suites.privcy]\nenabled = false\n",
                            name="typo.toml")),
            "--out", str(self.root / "out"))
        self.assertEqual(code, EXIT_CONFIG_ERROR)


class TheReportDisclosesIt(_Configured):
    def _audit(self) -> tuple[int, str, Path]:
        out = self.root / "out"
        code, stdout, _ = run_cli(
            "audit", "--config",
            str(self.config("[suites.smoke]\nenabled = true\nfloor = 1.0\n"
                            "[suites.privacy]\nenabled = false\n")),
            "--out", str(out))
        return code, stdout, next(out.glob("*/report.json"))

    def test_a_pass_from_a_partial_configuration_says_what_it_skipped(self):
        code, stdout, report_path = self._audit()
        self.assertEqual(code, EXIT_PASS)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["verdict"], "PASS")
        unscored = {e["suite"]: e["reason"] for e in report["scope"]["not_scored"]}
        self.assertEqual(unscored["privacy"], scope.DISABLED)
        self.assertEqual(unscored["adversarial"], scope.ABSENT)
        self.assertEqual(report["scope"]["scored"], 1)

    def test_the_build_log_says_it_too(self):
        # A verdict quoted out of its report loses the suite table with it,
        # and the build log is where that happens most.
        _, stdout, _ = self._audit()
        self.assertIn("NOT scored:", stdout)
        self.assertIn("privacy (disabled)", stdout)

    def test_the_markdown_report_carries_the_section(self):
        _, _, report_path = self._audit()
        markdown = (report_path.parent / "report.md").read_text(
            encoding="utf-8")
        self.assertIn("## Scope", markdown)
        self.assertIn("`privacy`", markdown)

    def test_the_seal_covers_it(self):
        # The disclosure is inside the report body, so it cannot be edited
        # off a written report without the report failing its own seal.
        _, _, report_path = self._audit()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        del report["scope"]
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        code, _, stderr = run_cli("verify", str(report_path))
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
        self.assertIn("does not match its own seal", stderr)


if __name__ == "__main__":
    unittest.main()
