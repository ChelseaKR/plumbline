"""Longitudinal run history: append-only recording, comparability across a
changed dataset or judge hash, and the plain decline-streak observation on
top — never a new statistic, never a vacuous trend."""

import json
import tempfile
import unittest
from pathlib import Path

from helpers import answer_item, response, run_cli, write_bundle
from plumbline.history import (
    HistoryError,
    append,
    load_history,
    trends,
)

CONFIG_TEMPLATE = """\
[target]
name = "history-test"

[dataset]
path = "{dataset_path}"

[judge]
kind = "lexical"

[suites.smoke]
enabled = true
floor = 1.0

[suites.accuracy]
enabled = true
floor = {floor}
"""


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.history_path = self.root / "history.json"

    def _report(self, response_text: str, *, name: str, floor: float = 0.5) -> Path:
        bundle_dir = write_bundle(
            self.root,
            [answer_item("a1", "the payment cap is 850 dollars")],
            [response("a1", response_text)],
            name=name,
        )
        config_path = self.root / f"{name}.toml"
        config_path.write_text(
            CONFIG_TEMPLATE.format(dataset_path=str(bundle_dir), floor=floor),
            encoding="utf-8")
        out_dir = self.root / f"{name}-audits"
        code, _, err = run_cli("audit", "--config", str(config_path),
                               "--out", str(out_dir))
        self.assertIn(code, (0, 1), err)
        return next(out_dir.iterdir()) / "report.json"

    def _read(self, path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # --- append -----------------------------------------------------------

    def test_append_creates_and_grows_the_history_file(self):
        report_path = self._report("the payment cap is 850 dollars", name="r1")
        runs, appended = append(self._read(report_path), self.history_path,
                                source=str(report_path))
        self.assertTrue(appended)
        self.assertEqual(len(runs), 1)
        self.assertTrue(self.history_path.exists())

    def test_appending_the_same_run_twice_is_a_no_op(self):
        report_path = self._report("the payment cap is 850 dollars", name="r1")
        report = self._read(report_path)
        append(report, self.history_path, source=str(report_path))
        runs, appended = append(report, self.history_path,
                                source=str(report_path))
        self.assertFalse(appended)
        self.assertEqual(len(runs), 1)

    def test_append_refuses_an_edited_report(self):
        report_path = self._report("the payment cap is 850 dollars", name="r1")
        report = self._read(report_path)
        report["verdict"] = "FAIL"  # moved: no longer matches its own seal
        from plumbline.report import ReportSealError
        with self.assertRaises(ReportSealError):
            append(report, self.history_path, source=str(report_path))

    def test_cli_append_and_check_roundtrip(self):
        report_path = self._report("the payment cap is 850 dollars", name="r1")
        code, out, err = run_cli("history", "append",
                                 "--report", str(report_path),
                                 "--history", str(self.history_path))
        self.assertEqual(code, 0, err)
        self.assertIn("appended:", out)

        code, out, err = run_cli("history", "check",
                                 "--history", str(self.history_path))
        self.assertEqual(code, 0, err)
        self.assertIn("history:", out)

    # --- comparability ------------------------------------------------

    def test_a_changed_dataset_breaks_the_comparable_chain(self):
        first = self._report("the payment cap is 850 dollars", name="r1")
        append(self._read(first), self.history_path, source=str(first))
        # A different bundle -> a different dataset hash.
        second_bundle = write_bundle(
            self.root, [answer_item("a1", "the cap is 850 dollars, revised")],
            [response("a1", "the cap is 850 dollars, revised")],
            name="different-dataset")
        config2 = self.root / "second.toml"
        config2.write_text(CONFIG_TEMPLATE.format(
            dataset_path=str(second_bundle), floor=0.5), encoding="utf-8")
        out2 = self.root / "second-audits"
        run_cli("audit", "--config", str(config2), "--out", str(out2))
        second = next(out2.iterdir()) / "report.json"
        runs, _ = append(self._read(second), self.history_path, source=str(second))

        result = trends(runs, min_streak=1)
        self.assertEqual(result["chain_len"], 1)
        self.assertFalse(result["comparable"])

    # --- decline detection ----------------------------------------------

    def test_three_identical_real_runs_are_not_a_decline(self):
        """A real run, appended three times over, must not read as a trend
        in either direction — only `run_id` differs between the entries,
        because each run is a byte-identical re-run of the same config."""
        bundle_dir = write_bundle(
            self.root, [answer_item("a1", "the payment cap is 850 dollars")],
            [response("a1", "the payment cap is 850 dollars")], name="stable")
        config = self.root / "stable.toml"
        config.write_text(CONFIG_TEMPLATE.format(
            dataset_path=str(bundle_dir), floor=0.1), encoding="utf-8")

        history_path = self.root / "flat-history.json"
        for i in range(3):
            out_dir = self.root / f"stable-audits-{i}"
            run_cli("audit", "--config", str(config), "--out", str(out_dir))
            report_path = next(out_dir.iterdir()) / "report.json"
            report = self._read(report_path)
            # Every re-run of an unchanged config is byte-identical, so
            # `run_id` collides too; force distinct ids the way a caller
            # comparing runs from different code or seeds would see them,
            # without touching anything `record_from_report` reads from the
            # sealed body.
            report = dict(report)
            report["provenance"] = dict(report["provenance"])
            report["provenance"]["run_id"] = f"stable-{i}"
            from plumbline.report import seal_report
            seal_report(report)
            append(report, history_path, source=str(report_path))

        runs = load_history(history_path)
        result = trends(runs, min_streak=3)
        self.assertEqual(result["chain_len"], 3)
        self.assertEqual(result["declining"], [],
                         "three identical runs must not read as a decline")

    def test_trends_flags_a_synthetic_declining_sequence(self):
        """Exercises the trend logic directly over hand-built compact
        records — the shape `record_from_report` produces — since driving a
        real monotonic decline through the harness would need a live target
        answering worse on each of several real runs."""
        def record(run_id: str, score: float) -> dict:
            return {
                "run_id": run_id, "target": "t", "verdict": "PASS",
                "dataset_sha256": "d" * 64, "dataset_id": "d" * 12,
                "judge_config_sha256": "j" * 64, "harness_version": "0.1.0",
                "suites": {"accuracy": {"score": score, "floor": 0.5,
                                        "mde": 0.01}},
            }
        runs = [record("r1", 0.95), record("r2", 0.90), record("r3", 0.85)]
        result = trends(runs, min_streak=3)
        self.assertEqual(result["chain_len"], 3)
        self.assertEqual(len(result["declining"]), 1)
        self.assertEqual(result["declining"][0]["suite"], "accuracy")
        self.assertEqual(result["declining"][0]["scores"], [0.95, 0.90, 0.85])

    def test_trends_does_not_flag_a_flat_or_recovering_sequence(self):
        def record(run_id: str, score: float) -> dict:
            return {
                "run_id": run_id, "target": "t", "verdict": "PASS",
                "dataset_sha256": "d" * 64, "dataset_id": "d" * 12,
                "judge_config_sha256": "j" * 64, "harness_version": "0.1.0",
                "suites": {"accuracy": {"score": score, "floor": 0.5,
                                        "mde": 0.01}},
            }
        runs = [record("r1", 0.90), record("r2", 0.80), record("r3", 0.90)]
        result = trends(runs, min_streak=3)
        self.assertEqual(result["declining"], [])

    def test_short_chain_reports_no_finding_rather_than_a_vacuous_one(self):
        def record(run_id: str, score: float) -> dict:
            return {
                "run_id": run_id, "target": "t", "verdict": "PASS",
                "dataset_sha256": "d" * 64, "dataset_id": "d" * 12,
                "judge_config_sha256": "j" * 64, "harness_version": "0.1.0",
                "suites": {"accuracy": {"score": score, "floor": 0.5,
                                        "mde": 0.01}},
            }
        runs = [record("r1", 0.95), record("r2", 0.80)]
        result = trends(runs, min_streak=3)
        self.assertEqual(result["chain_len"], 2)
        self.assertEqual(result["declining"], [])

    def test_cli_fail_on_decline_exits_nonzero(self):
        history_path = self.root / "declining.json"
        runs = [
            {"run_id": "r1", "target": "t", "verdict": "PASS",
             "dataset_sha256": "d" * 64, "dataset_id": "d" * 12,
             "judge_config_sha256": "j" * 64, "harness_version": "0.1.0",
             "suites": {"accuracy": {"score": s, "floor": 0.5, "mde": 0.01}}}
            for s in (0.95, 0.90, 0.85)
        ]
        for i, r in enumerate(runs):
            r["run_id"] = f"r{i}"
        from plumbline.history import write_history
        write_history(runs, history_path)

        code, out, err = run_cli("history", "check",
                                 "--history", str(history_path),
                                 "--min-streak", "3")
        self.assertEqual(code, 0, err)  # not asked to fail

        code, out, err = run_cli("history", "check",
                                 "--history", str(history_path),
                                 "--min-streak", "3", "--fail-on-decline")
        self.assertNotEqual(code, 0)
        self.assertIn("declined every run", out)

    def test_malformed_history_file_is_a_configuration_error(self):
        bad = self.root / "bad.json"
        bad.write_text('{"not": "a history file"}', encoding="utf-8")
        with self.assertRaises(HistoryError):
            load_history(bad)


if __name__ == "__main__":
    unittest.main()
