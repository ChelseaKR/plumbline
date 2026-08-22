"""Recording retention and redaction: screening reuses the privacy suite's
own PII patterns; a bundle past its retention window with an unredacted
finding refuses rather than being scored quietly clean by omission."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import answer_item, response, run_cli, write_bundle
from plumbline.bundle import load as load_bundle
from plumbline.bundle import seal as seal_bundle
from plumbline.retention import RetentionError, age_days, retire, screen


def _make_recorded_bundle(root: Path, items, responses, *, recorded_at: str,
                          name: str = "recorded") -> Path:
    bundle_dir = write_bundle(root, items, responses, name=name)
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["recording"] = {
        "mode": "live",
        "recorded_at": recorded_at,
        "harness_version": "0.1.0.dev0",
        "adapter": {"kind": "http_json", "endpoint": "https://example.invalid/chat"},
        "questions": {"name": "q", "version": "0.0.1", "sha256": "a" * 64,
                      "items": len(items)},
        "responses_recorded": len(responses),
        "responses_recorded_empty": [],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
    seal_bundle(bundle_dir)
    return bundle_dir


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    # --- prerequisites ------------------------------------------------

    def test_a_non_recorded_bundle_is_refused(self):
        bundle_dir = write_bundle(
            self.root, [answer_item("a1", "the cap is 850 dollars")],
            [response("a1", "the cap is 850 dollars")])
        with self.assertRaises(RetentionError):
            retire(bundle_dir, max_age_days=30)

    # --- screening ------------------------------------------------------

    def test_screen_finds_a_planted_ssn(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "your caseworker is on file")],
            [response("a1", "your case is linked to SSN 123-45-6789")],
            recorded_at=_iso(1))
        bundle = load_bundle(bundle_dir)
        findings = screen(bundle)
        self.assertIn("a1", findings)
        self.assertIn(("ssn", "123-45-6789"), findings["a1"])

    def test_screen_finds_nothing_in_a_clean_response(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "the cap is 850 dollars")],
            [response("a1", "the cap is 850 dollars")],
            recorded_at=_iso(1))
        bundle = load_bundle(bundle_dir)
        self.assertEqual(screen(bundle), {})

    # --- within the retention window: report, never fatal ---------------

    def test_a_finding_within_the_window_is_reported_not_refused(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "case detail")],
            [response("a1", "SSN on file: 123-45-6789")],
            recorded_at=_iso(1))
        result = retire(bundle_dir, max_age_days=30)
        self.assertEqual(result.redacted_count, 0)
        self.assertIn("a1", result.findings)

    # --- past the window: refuse unless redacted -------------------------

    def test_a_finding_past_the_window_without_redact_refuses(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "case detail")],
            [response("a1", "SSN on file: 123-45-6789")],
            recorded_at=_iso(90))
        with self.assertRaises(RetentionError):
            retire(bundle_dir, max_age_days=30)

    def test_a_clean_bundle_past_the_window_is_not_refused(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "the cap is 850 dollars")],
            [response("a1", "the cap is 850 dollars")],
            recorded_at=_iso(90))
        result = retire(bundle_dir, max_age_days=30)
        self.assertEqual(result.findings, {})
        self.assertEqual(result.redacted_count, 0)

    def test_redact_past_the_window_brings_it_into_compliance(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "case detail")],
            [response("a1", "SSN on file: 123-45-6789, call back soon")],
            recorded_at=_iso(90))
        result = retire(bundle_dir, max_age_days=30, redact_now=True)
        self.assertEqual(result.redacted_count, 1)

        # The rewritten bundle re-seals clean, and re-screening it finds
        # nothing left to flag.
        bundle = load_bundle(bundle_dir)
        self.assertNotIn("123-45-6789", bundle.response_for("a1"))
        self.assertIn("[REDACTED:ssn]", bundle.response_for("a1"))
        self.assertEqual(screen(bundle), {})

        # Retiring again, still past the window, no longer refuses: the
        # trace (a changed dataset hash) is what proves this happened.
        retire(bundle_dir, max_age_days=30)  # must not raise

    def test_redact_within_the_window_is_still_allowed(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "case detail")],
            [response("a1", "SSN on file: 123-45-6789")],
            recorded_at=_iso(1))
        result = retire(bundle_dir, max_age_days=30, redact_now=True)
        self.assertEqual(result.redacted_count, 1)

    def test_redaction_changes_the_dataset_hash(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "case detail")],
            [response("a1", "SSN on file: 123-45-6789")],
            recorded_at=_iso(1))
        before = load_bundle(bundle_dir).dataset_sha256
        retire(bundle_dir, max_age_days=30, redact_now=True)
        after = load_bundle(bundle_dir).dataset_sha256
        self.assertNotEqual(before, after)

    # --- age computation --------------------------------------------------

    def test_age_days_reads_the_recording_timestamp(self):
        recorded_at = _iso(5)
        age = age_days({"recorded_at": recorded_at})
        self.assertAlmostEqual(age, 5.0, delta=0.01)

    def test_missing_timestamp_refuses(self):
        with self.assertRaises(RetentionError):
            age_days({})

    # --- CLI ---------------------------------------------------------------

    def test_cli_retire_reports_within_window(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "case detail")],
            [response("a1", "SSN on file: 123-45-6789")],
            recorded_at=_iso(1))
        code, out, err = run_cli("retire", str(bundle_dir),
                                 "--max-age-days", "30")
        self.assertEqual(code, 0, err)
        self.assertIn("flagged:", out)
        self.assertIn("a1", out)

    def test_cli_retire_refuses_past_window(self):
        from plumbline.cli import EXIT_CONFIG_ERROR

        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "case detail")],
            [response("a1", "SSN on file: 123-45-6789")],
            recorded_at=_iso(90))
        code, out, err = run_cli("retire", str(bundle_dir),
                                 "--max-age-days", "30")
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("CONFIGURATION ERROR", err)

    def test_cli_retire_redact_flag_clears_it(self):
        bundle_dir = _make_recorded_bundle(
            self.root,
            [answer_item("a1", "case detail")],
            [response("a1", "SSN on file: 123-45-6789")],
            recorded_at=_iso(90))
        code, out, err = run_cli("retire", str(bundle_dir),
                                 "--max-age-days", "30", "--redact")
        self.assertEqual(code, 0, err)
        self.assertIn("redacted:", out)


if __name__ == "__main__":
    unittest.main()
