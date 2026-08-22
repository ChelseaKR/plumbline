"""Detached report signatures: sign, verify, and every way a signature check
must refuse rather than pass quietly.

Mirrors CONTRIBUTING.md's rule for a new gate: not only a test proving it
passes on good input, but tests proving it fails on a wrong key, a tampered
signature, and a report edited after it was signed.
"""

import json
import tempfile
import unittest
from pathlib import Path

from plumbline.report import build_report, write_reports
from plumbline.signing import (
    SignatureMismatchError,
    SigningError,
    key_id,
    read_key,
    read_signature,
    sign_report,
    verify_signature,
    write_signature,
)

CONFIG_TEMPLATE = """\
[target]
name = "signing-test"

[dataset]
path = "{dataset_path}"

[judge]
kind = "lexical"

[suites.smoke]
enabled = true
floor = 1.0
"""


def _report() -> dict:
    return build_report(
        verdict="PASS",
        provenance={
            "run_id": "abc123", "harness_version": "0.1.0.dev0",
            "seed": 1729, "dataset_sha256": "d" * 64, "dataset_id": "d" * 12,
            "judge_kind": "lexical", "judge_config_sha256": "e" * 64,
        },
        judge={"kind": "lexical", "deterministic": True},
        target="unit-test-target",
        dataset_info={"name": "fixture", "items": 1, "synthetic": True},
        results=[],
        warnings=[],
    )


class SigningTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.key_path = self.tmp / "key.bin"
        self.key_path.write_bytes(b"a" * 32)
        self.other_key_path = self.tmp / "other-key.bin"
        self.other_key_path.write_bytes(b"b" * 32)

    # --- passing case ---------------------------------------------------

    def test_sign_then_verify_roundtrip(self):
        report = _report()
        json_path, _ = write_reports(report, self.tmp / "out")
        with open(json_path, encoding="utf-8") as f:
            written = json.load(f)

        key = read_key(self.key_path)
        signature = sign_report(written, key, source=str(json_path))
        sig_path = write_signature(signature, json_path)
        self.assertTrue(sig_path.exists())
        self.assertEqual(signature["algorithm"], "hmac-sha256")
        self.assertEqual(signature["key_id"], key_id(key))

        verified = verify_signature(written, key, read_signature(sig_path),
                                    source=str(json_path),
                                    signature_source=str(sig_path))
        self.assertEqual(verified, key_id(key))

    def _real_report(self) -> Path:
        """A report written by an actual `plumbline audit` run: `verify` and
        `sign` both check the run-id derivation, which a hand-built fixture
        report does not satisfy."""
        from helpers import answer_item, response, run_cli, write_bundle

        bundle_dir = write_bundle(
            self.tmp, [answer_item("a1", "the cap is 850 dollars")],
            [response("a1", "the cap is 850 dollars")],
        )
        config_path = self.tmp / "target.toml"
        config_path.write_text(
            CONFIG_TEMPLATE.format(dataset_path=str(bundle_dir)),
            encoding="utf-8")
        out_dir = self.tmp / "audits"
        code, _, err = run_cli("audit", "--config", str(config_path),
                               "--out", str(out_dir))
        self.assertEqual(code, 0, err)
        run_dirs = sorted(out_dir.iterdir())
        self.assertEqual(len(run_dirs), 1)
        return run_dirs[0] / "report.json"

    def test_cli_sign_and_verify(self):
        from helpers import run_cli

        json_path = self._real_report()
        code, out, err = run_cli("sign", str(json_path),
                                 "--key-file", str(self.key_path))
        self.assertEqual(code, 0, err)
        self.assertIn("signed:", out)
        self.assertTrue((json_path.parent / "report.sig").exists())

        code, out, err = run_cli("verify", str(json_path),
                                 "--key-file", str(self.key_path))
        self.assertEqual(code, 0, err)
        self.assertIn("signature: OK", out)

    # --- failure modes ---------------------------------------------------

    def test_verify_with_wrong_key_is_a_mismatch(self):
        report = _report()
        json_path, _ = write_reports(report, self.tmp / "out")
        with open(json_path, encoding="utf-8") as f:
            written = json.load(f)

        signing_key = read_key(self.key_path)
        signature = sign_report(written, signing_key, source=str(json_path))

        wrong_key = read_key(self.other_key_path)
        with self.assertRaises(SignatureMismatchError):
            verify_signature(written, wrong_key, signature,
                             source=str(json_path))

    def test_tampered_signature_is_a_mismatch(self):
        report = _report()
        json_path, _ = write_reports(report, self.tmp / "out")
        with open(json_path, encoding="utf-8") as f:
            written = json.load(f)

        key = read_key(self.key_path)
        signature = sign_report(written, key, source=str(json_path))
        tampered = dict(signature)
        tampered["signature"] = ("0" if tampered["signature"][0] != "0"
                                 else "1") + tampered["signature"][1:]

        with self.assertRaises(SignatureMismatchError):
            verify_signature(written, key, tampered, source=str(json_path))

    def test_report_edited_after_signing_refuses_before_the_signature_check(self):
        report = _report()
        json_path, _ = write_reports(report, self.tmp / "out")
        with open(json_path, encoding="utf-8") as f:
            written = json.load(f)

        key = read_key(self.key_path)
        signature = sign_report(written, key, source=str(json_path))

        edited = dict(written)
        edited["verdict"] = "FAIL"  # the body moved; the seal no longer matches
        from plumbline.report import ReportSealError
        with self.assertRaises(ReportSealError):
            verify_signature(edited, key, signature, source=str(json_path))

    def test_signature_for_a_different_report_refuses(self):
        report_a = _report()
        report_b = _report()
        report_b["provenance"]["run_id"] = "different-run"
        path_a, _ = write_reports(report_a, self.tmp / "a")
        path_b, _ = write_reports(report_b, self.tmp / "b")
        with open(path_a, encoding="utf-8") as f:
            written_a = json.load(f)
        with open(path_b, encoding="utf-8") as f:
            written_b = json.load(f)

        key = read_key(self.key_path)
        signature_a = sign_report(written_a, key, source=str(path_a))
        with self.assertRaises(SignatureMismatchError):
            verify_signature(written_b, key, signature_a, source=str(path_b))

    def test_short_key_refused(self):
        short = self.tmp / "short.bin"
        short.write_bytes(b"tooshort")
        with self.assertRaises(SigningError):
            read_key(short)

    def test_empty_key_file_refused(self):
        empty = self.tmp / "empty.bin"
        empty.write_bytes(b"")
        with self.assertRaises(SigningError):
            read_key(empty)

    def test_unknown_algorithm_refused(self):
        report = _report()
        json_path, _ = write_reports(report, self.tmp / "out")
        with open(json_path, encoding="utf-8") as f:
            written = json.load(f)
        key = read_key(self.key_path)
        signature = sign_report(written, key, source=str(json_path))
        signature["algorithm"] = "hmac-sha512"
        with self.assertRaises(SigningError):
            verify_signature(written, key, signature, source=str(json_path))

    def test_sign_refuses_an_unsealed_report(self):
        report = _report()
        # No seal: report.py's provenance["report_sha256"] is only added by
        # seal_report/write_reports.
        key = read_key(self.key_path)
        from plumbline.report import ReportSealError
        with self.assertRaises(ReportSealError):
            sign_report(report, key)

    def test_cli_verify_with_wrong_key_exits_integrity_refusal(self):
        from helpers import run_cli
        from plumbline.cli import EXIT_INTEGRITY_REFUSAL

        json_path = self._real_report()
        code, _, _ = run_cli("sign", str(json_path),
                             "--key-file", str(self.key_path))
        self.assertEqual(code, 0)

        code, out, err = run_cli("verify", str(json_path),
                                 "--key-file", str(self.other_key_path))
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
        self.assertIn("SIGNATURE REFUSAL", err)


if __name__ == "__main__":
    unittest.main()
