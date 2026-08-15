"""Baseline regression comparison: what moved, what flipped, and when the
harness refuses to subtract two numbers that were never comparable."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from plumbline.baseline import (
    BaselineError,
    build_baseline,
    compare,
    load_baseline,
    write_baseline,
)
from plumbline.cli import (
    EXIT_CONFIG_ERROR,
    EXIT_PASS,
    EXIT_SUITE_FAILURE,
    main,
)

from helpers import answer_item, refuse_item, response, write_bundle

CONFIG_TEMPLATE = """\
[target]
name = "baseline-test"

[dataset]
path = "{dataset_path}"

[suites.smoke]
enabled = true
floor = 1.0

[suites.accuracy]
enabled = true
floor = 0.75
"""


def report_fixture(*, dataset="d" * 64, judge="j" * 64, verdict="PASS",
                   suites=None, harness="0.1.0.dev0", seed=1729):
    suites = suites if suites is not None else [
        {"suite": "accuracy", "score": 0.88, "floor": 0.75, "verdict": "PASS",
         "n": 18, "mde": 0.06},
        {"suite": "smoke", "score": 1.0, "floor": 1.0, "verdict": "PASS",
         "n": 26, "mde": 0.115},
    ]
    return {
        "verdict": verdict,
        "provenance": {
            "run_id": "0123456789abcdef",
            "harness_version": harness,
            "seed": seed,
            "dataset_sha256": dataset,
            "dataset_id": dataset[:12],
            "judge_config_sha256": judge,
        },
        "target": "baseline-test",
        "suites": suites,
    }


class BaselineRecordTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_record_carries_provenance_and_one_line_per_suite(self):
        record = build_baseline(report_fixture())
        self.assertEqual(record["format"], "plumbline-baseline")
        self.assertEqual(record["source_run_id"], "0123456789abcdef")
        self.assertEqual([s["suite"] for s in record["suites"]],
                         ["accuracy", "smoke"])
        # Per-item detail stays out: this is the bar, not the evidence.
        self.assertNotIn("items", record["suites"][0])

    def test_round_trip(self):
        path = write_baseline(build_baseline(report_fixture()),
                              self.root / "b.json")
        self.assertEqual(load_baseline(path)["source_run_id"],
                         "0123456789abcdef")

    def test_missing_file_is_an_error(self):
        with self.assertRaises(BaselineError):
            load_baseline(self.root / "absent.json")

    def test_a_report_is_not_a_baseline(self):
        path = self.root / "report.json"
        path.write_text(json.dumps(report_fixture()), encoding="utf-8")
        with self.assertRaises(BaselineError):
            load_baseline(path)

    def test_unsupported_format_version_is_an_error(self):
        record = build_baseline(report_fixture())
        record["format_version"] = 99
        path = write_baseline(record, self.root / "b.json")
        with self.assertRaises(BaselineError):
            load_baseline(path)


class ComparisonTests(unittest.TestCase):
    def test_identical_runs_report_nothing_moved(self):
        report = report_fixture()
        result = compare(report, build_baseline(report))
        self.assertTrue(result["comparable"])
        self.assertEqual(result["flipped_suites"], [])
        self.assertEqual(result["moved_suites"], [])
        self.assertEqual(result["summary"],
                         "no verdict changed and no score moved")

    def test_differing_dataset_hash_refuses_numeric_comparison(self):
        baseline = build_baseline(report_fixture(dataset="a" * 64))
        current = report_fixture(dataset="b" * 64)
        result = compare(current, baseline)
        self.assertFalse(result["comparable"])
        self.assertIsNone(result["moved_suites"])
        self.assertEqual(len(result["refusals"]), 1)
        self.assertIn("dataset hash differs", result["refusals"][0])
        self.assertIn("aaaaaaaaaaaa", result["refusals"][0])
        self.assertIn("bbbbbbbbbbbb", result["refusals"][0])

    def test_differing_judge_config_refuses_numeric_comparison(self):
        baseline = build_baseline(report_fixture(judge="a" * 64))
        result = compare(report_fixture(judge="b" * 64), baseline)
        self.assertFalse(result["comparable"])
        self.assertIn("judge configuration hash differs", result["refusals"][0])

    def test_verdict_flips_are_named_even_when_incomparable(self):
        baseline = build_baseline(report_fixture(dataset="a" * 64))
        current = report_fixture(
            dataset="b" * 64, verdict="FAIL",
            suites=[
                {"suite": "accuracy", "score": 0.86, "floor": 0.75,
                 "verdict": "FAIL", "n": 18, "mde": 0.06},
                {"suite": "smoke", "score": 1.0, "floor": 1.0,
                 "verdict": "PASS", "n": 26, "mde": 0.115},
            ])
        result = compare(current, baseline)
        self.assertFalse(result["comparable"])
        self.assertEqual(result["flipped_suites"],
                         [{"suite": "accuracy", "was": "PASS", "now": "FAIL"}])
        self.assertEqual(result["verdict_change"],
                         {"was": "PASS", "now": "FAIL"})

    def test_a_move_smaller_than_the_mde_is_reported_as_noise(self):
        baseline = build_baseline(report_fixture())
        current = report_fixture(suites=[
            {"suite": "accuracy", "score": 0.86, "floor": 0.75,
             "verdict": "PASS", "n": 18, "mde": 0.06},
            {"suite": "smoke", "score": 1.0, "floor": 1.0,
             "verdict": "PASS", "n": 26, "mde": 0.115},
        ])
        moved = compare(current, baseline)["moved_suites"]
        self.assertEqual(len(moved), 1)
        self.assertAlmostEqual(moved[0]["delta"], -0.02)
        self.assertFalse(moved[0]["detectable"])
        self.assertIn("not distinguishable", moved[0]["note"])

    def test_a_move_larger_than_the_mde_is_reported_as_detectable(self):
        baseline = build_baseline(report_fixture())
        current = report_fixture(suites=[
            {"suite": "accuracy", "score": 0.60, "floor": 0.75,
             "verdict": "FAIL", "n": 18, "mde": 0.06},
            {"suite": "smoke", "score": 1.0, "floor": 1.0,
             "verdict": "PASS", "n": 26, "mde": 0.115},
        ])
        moved = compare(current, baseline)["moved_suites"]
        self.assertTrue(moved[0]["detectable"])
        self.assertNotIn("note", moved[0])

    def test_added_and_removed_suites_are_named(self):
        baseline = build_baseline(report_fixture())
        current = report_fixture(suites=[
            {"suite": "smoke", "score": 1.0, "floor": 1.0, "verdict": "PASS",
             "n": 26, "mde": 0.115},
            {"suite": "privacy", "score": 1.0, "floor": 1.0, "verdict": "PASS",
             "n": 26, "mde": 0.115},
        ])
        result = compare(current, baseline)
        self.assertEqual(result["added_suites"], ["privacy"])
        self.assertEqual(result["removed_suites"], ["accuracy"])

    def test_a_moved_floor_is_a_caveat_not_a_refusal(self):
        baseline = build_baseline(report_fixture())
        current = report_fixture(suites=[
            {"suite": "accuracy", "score": 0.88, "floor": 0.60,
             "verdict": "PASS", "n": 18, "mde": 0.06},
            {"suite": "smoke", "score": 1.0, "floor": 1.0, "verdict": "PASS",
             "n": 26, "mde": 0.115},
        ])
        result = compare(current, baseline)
        self.assertTrue(result["comparable"])
        self.assertTrue(any("floors changed" in c for c in result["caveats"]))

    def test_a_harness_version_change_is_a_caveat(self):
        baseline = build_baseline(report_fixture(harness="0.1.0.dev0"))
        result = compare(report_fixture(harness="0.2.0"), baseline)
        self.assertTrue(result["comparable"])
        self.assertTrue(any("harness version differs" in c
                            for c in result["caveats"]))


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class BaselineCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.out_dir = self.root / "audits"
        self.bundle_dir = write_bundle(
            self.root,
            [answer_item("a1", "the payment cap is 850 dollars"),
             refuse_item("r1")],
            [response("a1", "the payment cap is 850 dollars"),
             response("r1", "I can't help with that.")],
        )
        self.config_path = self.root / "target.toml"
        self.config_path.write_text(
            CONFIG_TEMPLATE.format(dataset_path=str(self.bundle_dir)),
            encoding="utf-8",
        )
        self.baseline_path = self.root / "baseline.json"

    def _audit(self, *extra):
        return run_cli("audit", "--config", str(self.config_path),
                       "--out", str(self.out_dir), *extra)

    def _report(self):
        return json.loads(
            next(self.out_dir.rglob("report.json")).read_text(encoding="utf-8"))

    def _adopt_baseline(self):
        self._audit()
        code, _, _ = run_cli("baseline",
                             "--from", str(next(self.out_dir.rglob("report.json"))),
                             "--out", str(self.baseline_path))
        self.assertEqual(code, EXIT_PASS)
        self.assertTrue(self.baseline_path.is_file())

    def test_unchanged_run_reports_no_movement(self):
        self._adopt_baseline()
        code, out, _ = self._audit("--baseline", str(self.baseline_path))
        self.assertEqual(code, EXIT_PASS)
        self.assertIn("no verdict changed and no score moved", out)
        block = next(r for r in
                     (json.loads(p.read_text(encoding="utf-8"))
                      for p in self.out_dir.rglob("report.json"))
                     if r["baseline"])["baseline"]
        self.assertTrue(block["comparable"])

    def test_resealed_evidence_makes_the_baseline_incomparable(self):
        self._adopt_baseline()
        responses = self.bundle_dir / "responses.jsonl"
        responses.write_text(
            responses.read_text(encoding="utf-8").replace("850", "900"),
            encoding="utf-8")
        run_cli("seal", str(self.bundle_dir))
        code, out, _ = self._audit("--baseline", str(self.baseline_path))
        self.assertEqual(code, EXIT_PASS)  # the audit itself still passes
        self.assertIn("numeric comparison refused", out)
        self.assertIn("dataset hash differs", out)

    def test_require_comparable_baseline_turns_refusal_into_an_error(self):
        self._adopt_baseline()
        responses = self.bundle_dir / "responses.jsonl"
        responses.write_text(
            responses.read_text(encoding="utf-8").replace("850", "900"),
            encoding="utf-8")
        run_cli("seal", str(self.bundle_dir))
        code, _, err = self._audit("--baseline", str(self.baseline_path),
                                   "--require-comparable-baseline")
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("not comparable", err)

    def test_a_missing_baseline_is_an_error_not_a_skipped_extra(self):
        code, _, err = self._audit("--baseline", str(self.root / "nope.json"))
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("baseline file not found", err)

    def test_a_real_regression_flips_a_suite_and_fails_the_gate(self):
        self._adopt_baseline()
        responses = self.bundle_dir / "responses.jsonl"
        responses.write_text(
            responses.read_text(encoding="utf-8").replace(
                "the payment cap is 850 dollars", "no idea, sorry"),
            encoding="utf-8")
        run_cli("seal", str(self.bundle_dir))
        code, out, _ = self._audit("--baseline", str(self.baseline_path))
        self.assertEqual(code, EXIT_SUITE_FAILURE)
        self.assertIn("flipped: accuracy PASS -> FAIL", out)

    def test_reports_stay_byte_identical_with_a_baseline(self):
        self._adopt_baseline()
        self._audit("--baseline", str(self.baseline_path))
        paths = sorted(self.out_dir.rglob("report.*"))
        first = [p.read_bytes() for p in paths]
        self._audit("--baseline", str(self.baseline_path))
        self.assertEqual([p.read_bytes() for p in paths], first)

    def test_comparing_against_a_different_bar_is_a_different_run(self):
        # The baseline is an input to the run, so it belongs in the run id.
        self._adopt_baseline()
        without = set(p.parent.name for p in self.out_dir.rglob("report.json"))
        self._audit("--baseline", str(self.baseline_path))
        withall = set(p.parent.name for p in self.out_dir.rglob("report.json"))
        self.assertTrue(withall - without)

    def test_baseline_can_be_set_in_the_target_config(self):
        self._adopt_baseline()
        self.config_path.write_text(
            self.config_path.read_text(encoding="utf-8")
            + f'\n[baseline]\npath = "{self.baseline_path}"\n',
            encoding="utf-8")
        code, out, _ = self._audit()
        self.assertEqual(code, EXIT_PASS)
        self.assertIn("baseline:", out)


if __name__ == "__main__":
    unittest.main()
