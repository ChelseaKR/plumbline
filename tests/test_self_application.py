"""Plumbline held to its own standard.

The harness demands provenance-stamped, hash-protected, reproducible evidence
from the systems it grades. This file checks that the evidence *this
repository* commits meets the same bar, because a committed report that no
longer matches the code is the exact failure mode the tool exists to prevent —
it looks like a verdict and is a memory.

Four committed artifacts, and what has to be true of each:

- `datasets/riverbend-demo/` — reproducible from its generator, and sealed.
  (`tests/test_demo_bundle.py`.)
- `audits/<run-id>/report.{json,md}` — byte-identical to what the shipped
  command produces today, and the only audit directory in the repository.
- `baselines/riverbend-demo.json` — describing the evidence and the instrument
  that actually exist.
- `proof/matrix.{json,md}` — current. (`tests/test_defect_matrix.py`.)
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import run_cli

from plumbline import __version__
from plumbline.bundle import load as load_bundle
from plumbline.cli import EXIT_PASS
from plumbline.config import load_config
from plumbline.hashing import config_digest, source_digest
from plumbline.judges import make_judge

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "examples" / "riverbend.toml"
AUDITS = REPO / "audits"
BASELINE = REPO / "baselines" / "riverbend-demo.json"
PROOF = REPO / "proof" / "matrix.json"


def committed_report() -> dict:
    paths = sorted(AUDITS.glob("*/report.json"))
    if len(paths) != 1:
        raise AssertionError(
            f"expected exactly one committed audit report, found "
            f"{[str(p.relative_to(REPO)) for p in paths]}")
    return json.loads(paths[0].read_text(encoding="utf-8"))


class TheCommittedReportIsCurrent(unittest.TestCase):
    def test_exactly_one_audit_is_committed(self):
        # A stale run directory left behind from an earlier dataset is a
        # second, contradictory verdict sitting in the repository.
        runs = sorted(p.name for p in AUDITS.iterdir() if p.is_dir())
        self.assertEqual(len(runs), 1, runs)

    def test_rerunning_the_documented_command_reproduces_it_byte_for_byte(self):
        report = committed_report()
        run_id = report["provenance"]["run_id"]
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = run_cli("gate", "--config", CONFIG.as_posix(),
                                   "--out", tmp)
            self.assertEqual(code, EXIT_PASS, out)
            for name in ("report.json", "report.md"):
                fresh = (Path(tmp) / run_id / name).read_bytes()
                committed = (AUDITS / run_id / name).read_bytes()
                self.assertEqual(
                    fresh, committed,
                    f"audits/{run_id}/{name} is not what the shipped command "
                    f"produces today")

    def test_the_report_names_the_evidence_that_is_actually_committed(self):
        report = committed_report()
        bundle = load_bundle(load_config(CONFIG).dataset_path)
        self.assertEqual(report["provenance"]["dataset_sha256"],
                         bundle.dataset_sha256)
        self.assertEqual(report["dataset"]["items"], len(bundle.items))

    def test_the_report_names_the_instrument_that_actually_produced_it(self):
        report = committed_report()
        provenance = report["provenance"]
        self.assertEqual(provenance["harness_version"], __version__)
        self.assertEqual(provenance["harness_source_sha256"],
                         source_digest(Path(__file__).resolve().parent.parent
                                       / "src" / "plumbline"))
        judge, _ = make_judge(load_config(CONFIG).judge)
        self.assertEqual(provenance["judge_config_sha256"],
                         config_digest(judge.config()))

    def test_the_report_carries_every_provenance_field_the_spec_requires(self):
        provenance = committed_report()["provenance"]
        for field in ("run_id", "harness_version", "harness_source_sha256",
                      "seed", "dataset_sha256", "dataset_id",
                      "judge_config_sha256"):
            self.assertTrue(provenance.get(field) is not None, field)

    def test_the_report_carries_no_wall_clock_time(self):
        # Byte-reproducibility is the reason; this is the check that keeps it.
        # The word "timestamps" appears once, in the note explaining that
        # there are none, so the check is on the shape rather than the string.
        report = committed_report()
        flat = json.dumps({k: v for k, v in report.items() if k != "notes"})
        for banned in ("generated_at", "recorded_at", "created", "T00:",
                       "20" + "26-"):
            self.assertNotIn(banned, flat, banned)


class TheCommittedBaselineIsCurrent(unittest.TestCase):
    def setUp(self):
        self.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_it_is_a_regeneration_of_the_committed_report(self):
        """The whole file, not the three hashes the tests below name.

        Every other committed artifact here is held to "regenerate it and
        compare the bytes". The baseline was not: three of its fields were
        checked against the tree and the rest — the verdict, the target, and
        one line per suite with its score, floor, verdict and n — were
        whatever was last written there. A committed floor could have drifted
        from the report it was distilled from and nothing would have said so.

        One field is excluded, and only one: `source_run_id`. The regeneration
        loop in `docs/operations-runbook.md` makes it *necessarily* name a
        different run from the committed one — the baseline is built from a
        first gate run, and its own hash then feeds the run id of the second,
        which is the run that gets committed, so the run this baseline was
        distilled from is by construction the previous one. It is excluded by
        substituting the committed value rather than by dropping the key, so
        the comparison stays byte-for-byte over everything else, key order and
        formatting included.
        """
        from plumbline.baseline import build_baseline

        fresh = build_baseline(committed_report())
        self.assertIn("source_run_id", fresh)
        fresh["source_run_id"] = self.baseline.get("source_run_id")
        rendered = json.dumps(fresh, indent=2, ensure_ascii=False) + "\n"
        self.assertEqual(
            BASELINE.read_text(encoding="utf-8"), rendered,
            "baselines/riverbend-demo.json is not what the committed report "
            "distils to; regenerate it per docs/operations-runbook.md rather "
            "than editing it")

    def test_it_describes_the_evidence_that_is_actually_committed(self):
        bundle = load_bundle(load_config(CONFIG).dataset_path)
        self.assertEqual(self.baseline["dataset_sha256"], bundle.dataset_sha256)

    def test_it_describes_the_instrument_that_actually_exists(self):
        judge, _ = make_judge(load_config(CONFIG).judge)
        self.assertEqual(self.baseline["judge_config_sha256"],
                         config_digest(judge.config()))
        self.assertEqual(self.baseline["harness_source_sha256"],
                         source_digest(REPO / "src" / "plumbline"))

    def test_the_committed_run_compares_cleanly_against_it(self):
        # If it did not, the repository would be shipping a report whose own
        # regression block says the bar it is held to is unreachable.
        comparison = committed_report()["baseline"]
        self.assertTrue(comparison["comparable"], comparison)
        self.assertIsNone(comparison["verdict_change"])
        self.assertEqual(comparison["flipped_suites"], [])
        self.assertEqual(comparison["added_suites"], [])
        self.assertEqual(comparison["removed_suites"], [])


class TheProofIsAboutThisEvidence(unittest.TestCase):
    def test_the_matrix_control_run_used_the_committed_bundle(self):
        matrix = json.loads(PROOF.read_text(encoding="utf-8"))
        bundle = load_bundle(load_config(CONFIG).dataset_path)
        self.assertEqual(matrix["control"]["dataset_id"], bundle.dataset_id)
        self.assertEqual(matrix["harness_version"], __version__)
        self.assertEqual(matrix["harness_source_sha256"],
                         source_digest(REPO / "src" / "plumbline"))

    def test_the_matrix_covers_every_suite_the_committed_report_scored(self):
        matrix = json.loads(PROOF.read_text(encoding="utf-8"))
        scored = sorted(s["suite"] for s in committed_report()["suites"])
        self.assertEqual(matrix["suites_with_a_defect_case"], scored)


class TheHarnessSourceDigest(unittest.TestCase):
    def test_it_changes_when_the_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "plumbline"
            shutil.copytree(REPO / "src" / "plumbline", copy)
            before = source_digest(copy)
            (copy / "audit.py").write_text(
                (copy / "audit.py").read_text(encoding="utf-8") + "\n# edit\n",
                encoding="utf-8")
            self.assertNotEqual(source_digest(copy), before)

    def test_it_ignores_bytecode_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "plumbline"
            shutil.copytree(REPO / "src" / "plumbline", copy)
            before = source_digest(copy)
            cache = copy / "__pycache__"
            cache.mkdir(exist_ok=True)
            (cache / "audit.cpython-312.py").write_text("x", encoding="utf-8")
            self.assertEqual(source_digest(copy), before)

    def test_it_reports_absence_rather_than_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(source_digest(Path(tmp) / "not-there"))
            self.assertIsNone(source_digest(Path(tmp)))

    def test_a_changed_harness_source_is_a_named_caveat_not_a_refusal(self):
        from plumbline.baseline import compare
        report = committed_report()
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        baseline["harness_source_sha256"] = "0" * 64
        comparison = compare(report, baseline)
        self.assertTrue(comparison["comparable"])
        self.assertTrue(any("harness source differs" in c
                            for c in comparison["caveats"]), comparison)


if __name__ == "__main__":
    unittest.main()
