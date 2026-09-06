"""`plumbline compare`: several targets, one question set.

The integration cases drive real audits over real sealed bundles, because the property worth
having is that the comparison matches what the harness recorded, not what a fixture asserts.

The unit cases below them build reports by hand on purpose. Each is about a shape the demo
data cannot produce on demand -- a suite with no score, a suite with no minimum detectable
effect -- and those are exactly the shapes where a comparison must refuse rather than return
a neutral-looking answer.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from plumbline.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_SUITE_FAILURE
from plumbline.compare import CompareError, TargetRun, compare_runs

from helpers import answer_item, response, run_cli, write_bundle

CONFIG = """\
[target]
name = "{name}"

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

[suites.groundedness]
enabled = true
floor = 0.70
"""

#: Twelve questions. Small enough to audit quickly, large enough that a defect on half of them
#: clears the suite's minimum detectable effect while an identical rerun does not.
FACTS = [
    ("rent-cap", "The rent cap is 850 dollars per month."),
    ("deadline", "The deadline is the fifteenth of March."),
    ("hearing", "The hearing is held on a Tuesday."),
    ("appeal", "An appeal must be filed within thirty days."),
    ("fee", "The filing fee is 40 dollars."),
    ("office", "The office opens at nine in the morning."),
    ("notice", "Notice must be given fourteen days ahead."),
    ("permit", "A permit lasts for twelve months."),
    ("renewal", "Renewal costs 25 dollars."),
    ("limit", "The limit is five applications a year."),
    ("window", "The window closes at four in the afternoon."),
    ("waiver", "A waiver is granted for six months."),
]

SOURCES = [{"id": f"src-{k}", "text": t} for k, t in FACTS]
ITEMS = [answer_item(k, t, sources=[f"src-{k}"]) for k, t in FACTS]
GOOD = [response(k, t) for k, t in FACTS]
#: The same answers, except the first six are answers to nothing that was asked. Half the set
#: wrong is a large defect on purpose: at n = 12 a suite scoring a perfect 1.0 reports a
#: minimum detectable effect of 3/12 = 0.25 under the rule of three, so a subtler defect is
#: genuinely inside the noise and this fixture would be asserting that the verb lies. The
#: real tamper drill's three-in-108 defect is inside the noise for the same reason, and the
#: verb says so; see the pull request for #64.
WRONG = "I do not have that information available in this conversation."
PLANTED = [
    response(k, WRONG) if i < 6 else response(k, t)
    for i, (k, t) in enumerate(FACTS)
]


def _config(root: Path, name: str, bundle: Path) -> Path:
    path = root / f"{name}.toml"
    path.write_text(CONFIG.format(name=name, dataset_path=bundle), encoding="utf-8")
    return path


def _comparison(out: Path) -> dict:
    return json.loads((out / "comparison.json").read_text(encoding="utf-8"))


def _pairs(comparison: dict, suite: str) -> list[dict]:
    entry = next(s for s in comparison["suites"] if s["suite"] == suite)
    return list(entry["pairs"])


def _synthetic(suites_a: list[dict], suites_b: list[dict]) -> list[TargetRun]:
    """Two runs over one question set, differing only in what their suites recorded."""
    def report(name: str, suites: list[dict]) -> dict:
        return {
            "verdict": "PASS",
            "provenance": {
                "run_id": f"run-{name}", "dataset_id": f"ds-{name}",
                "dataset_sha256": f"{name}-dataset", "judge_config_sha256": "judge",
                "harness_source_sha256": "src", "seed": 1729,
            },
            "target": name, "suites": suites, "couplings": None,
        }
    return [
        TargetRun(position=1, name="a", config="a.toml", report=report("a", suites_a),
                  question_set_sha256="q" * 64),
        TargetRun(position=2, name="b", config="b.toml", report=report("b", suites_b),
                  question_set_sha256="q" * 64),
    ]


def _suite(name: str, *, score, n: int = 10, mde, verdict: str = "PASS",
           items: list[dict] | None = None) -> dict:
    return {"suite": name, "score": score, "floor": 0.5, "verdict": verdict, "n": n,
            "ci": None, "mde": mde, "stats": {}, "details": {},
            "hard_failures": [], "items": items or []}


class ComparingRealAudits(unittest.TestCase):
    """The four acceptance criteria from the issue, over real runs."""

    def test_identical_configurations_report_every_delta_inside_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = write_bundle(root, ITEMS, GOOD, sources=SOURCES, name="q")
            a, b = _config(root, "alpha", bundle), _config(root, "beta", bundle)
            out = root / "out"
            code, _, _ = run_cli("compare", "--config", str(a), "--config", str(b),
                                 "--out", str(out))
            self.assertEqual(code, EXIT_PASS)
            comparison = _comparison(out)
            labels = [p["label"] for s in comparison["suites"] for p in s["pairs"]]
            self.assertTrue(labels, "no pair was compared; this check would pass over nothing")
            self.assertNotIn("distinguishable", labels)
            self.assertIn("inside noise", labels)

    def test_a_different_question_set_exits_4_naming_the_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = write_bundle(root, ITEMS, GOOD, sources=SOURCES, name="q1")
            reworded = [dict(i, prompt=i["prompt"] + " (reworded)") if n == 0 else i
                        for n, i in enumerate(ITEMS)]
            second = write_bundle(root, reworded, GOOD, sources=SOURCES, name="q2")
            a, b = _config(root, "alpha", first), _config(root, "beta", second)
            code, out_text, err = run_cli("compare", "--config", str(a), "--config", str(b),
                                          "--out", str(root / "out"))
            self.assertEqual(code, EXIT_CONFIG_ERROR)
            self.assertEqual(out_text, "")
            self.assertIn("the question set differs", err)
            # Both identities are named, so a reader can act on the message.
            self.assertIn("dataset", err)

    def test_a_planted_defect_is_distinguishable_where_it_lands_and_not_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean = write_bundle(root, ITEMS, GOOD, sources=SOURCES, name="clean")
            spoilt = write_bundle(root, ITEMS, PLANTED, sources=SOURCES, name="spoilt")
            a, b = _config(root, "alpha", clean), _config(root, "beta", spoilt)
            out = root / "out"
            code, _, _ = run_cli("compare", "--config", str(a), "--config", str(b),
                                 "--out", str(out))
            self.assertIn(code, (EXIT_PASS, EXIT_SUITE_FAILURE))
            comparison = _comparison(out)
            self.assertEqual([p["label"] for p in _pairs(comparison, "accuracy")],
                             ["distinguishable"])
            # `smoke` scores whether a response exists at all, which the defect does not touch.
            self.assertEqual([p["label"] for p in _pairs(comparison, "smoke")],
                             ["inside noise"])

    def test_three_configs_render_three_columns_and_three_pairwise_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = write_bundle(root, ITEMS, GOOD, sources=SOURCES, name="q")
            configs = [_config(root, name, bundle) for name in ("alpha", "beta", "gamma")]
            out = root / "out"
            argv = ["compare"]
            for config in configs:
                argv += ["--config", str(config)]
            code, _, _ = run_cli(*argv, "--out", str(out))
            self.assertEqual(code, EXIT_PASS)
            comparison = _comparison(out)
            self.assertEqual(len(comparison["targets"]), 3)
            entry = next(s for s in comparison["suites"] if s["suite"] == "accuracy")
            self.assertEqual(len(entry["columns"]), 3)
            self.assertEqual(len(entry["pairs"]), 3)

    def test_the_targets_keep_the_order_they_were_given_and_nothing_is_ranked(self) -> None:
        """"There is no ranking column, because this is not a leaderboard.\""""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean = write_bundle(root, ITEMS, GOOD, sources=SOURCES, name="clean")
            spoilt = write_bundle(root, ITEMS, PLANTED, sources=SOURCES, name="spoilt")
            # The worse target first: a ranking would reorder them.
            b, a = _config(root, "beta", spoilt), _config(root, "alpha", clean)
            out = root / "out"
            run_cli("compare", "--config", str(b), "--config", str(a), "--out", str(out))
            comparison = _comparison(out)
            self.assertEqual([t["name"] for t in comparison["targets"]], ["beta", "alpha"])
            rendered = json.dumps(comparison)
            for word in ("rank", "winner", "best", "composite"):
                self.assertNotIn(f'"{word}"', rendered)

    def test_output_is_byte_identical_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = write_bundle(root, ITEMS, GOOD, sources=SOURCES, name="q")
            a, b = _config(root, "alpha", bundle), _config(root, "beta", bundle)
            first_out, second_out = root / "one", root / "two"
            run_cli("compare", "--config", str(a), "--config", str(b), "--out", str(first_out))
            run_cli("compare", "--config", str(a), "--config", str(b), "--out", str(second_out))
            for name in ("comparison.json", "comparison.md"):
                self.assertEqual((first_out / name).read_text(encoding="utf-8"),
                                 (second_out / name).read_text(encoding="utf-8"))


class WhatCannotBeComparedIsRefused(unittest.TestCase):
    """A comparison that cannot be made must not return a neutral-looking answer.

    Each case here is a shape where the safest-sounding output -- a delta of zero, or "inside
    noise" -- would be a claim nobody computed.
    """

    def test_a_suite_with_no_score_gets_no_delta_rather_than_a_zero(self) -> None:
        runs = _synthetic(
            [_suite("accuracy", score=0.9, mde=0.1)],
            [_suite("accuracy", score=None, mde=None)],
        )
        pair = compare_runs(runs)["suites"][0]["pairs"][0]
        self.assertIsNone(pair["delta"], "an absent score was subtracted into a number")
        self.assertEqual(pair["label"], "not comparable")
        self.assertIn("not a difference of zero", pair["note"])

    def test_a_suite_with_no_mde_is_not_qualifiable_rather_than_inside_noise(self) -> None:
        """`inside noise` claims the difference is smaller than the sample can detect. A suite
        reporting no minimum detectable effect has made no such claim."""
        runs = _synthetic(
            [_suite("census", score=1.0, mde=None)],
            [_suite("census", score=1.0, mde=None)],
        )
        pair = compare_runs(runs)["suites"][0]["pairs"][0]
        self.assertEqual(pair["delta"], 0.0)
        self.assertEqual(pair["label"], "not qualifiable")
        self.assertNotEqual(pair["label"], "inside noise")

    def test_a_suite_one_target_did_not_score_is_named_and_never_paired(self) -> None:
        runs = _synthetic(
            [_suite("accuracy", score=0.9, mde=0.1), _suite("refusal", score=1.0, mde=0.2)],
            [_suite("accuracy", score=0.9, mde=0.1)],
        )
        entry = next(s for s in compare_runs(runs)["suites"] if s["suite"] == "refusal")
        self.assertEqual(entry["not_scored_by"], ["2. b"])
        self.assertEqual(entry["pairs"], [],
                         "a suite only one target scored was given a delta")
        self.assertIn("not a difference", entry["note"])

    def test_a_comparable_pair_survives_a_third_target_that_did_not_score_the_suite(self) -> None:
        """Refusing the pairs that cannot be made must not throw away the ones that can."""
        runs = _synthetic(
            [_suite("accuracy", score=0.9, mde=0.1)],
            [_suite("accuracy", score=0.9, mde=0.1)],
        )
        runs.append(TargetRun(position=3, name="c", config="c.toml",
                              question_set_sha256="q" * 64,
                              report={"verdict": "PASS", "target": "c", "couplings": None,
                                      "provenance": runs[0].report["provenance"],
                                      "suites": []}))
        entry = compare_runs(runs)["suites"][0]
        self.assertEqual(entry["not_scored_by"], ["3. c"])
        self.assertEqual([(p["left"], p["right"]) for p in entry["pairs"]],
                         [("1. a", "2. b")])

    def test_the_threshold_is_derived_from_both_samples_not_picked_from_one(self) -> None:
        """`sqrt((mde_a^2 + mde_b^2) / 2)`, the standard error of the difference expressed in
        the two MDEs the report already carries. Literals here, not the formula: a test that
        recomputes the implementation cannot disagree with it."""
        runs = _synthetic(
            [_suite("accuracy", score=0.50, mde=0.05, n=400)],
            [_suite("accuracy", score=0.60, mde=0.20, n=20)],
        )
        pair = compare_runs(runs)["suites"][0]["pairs"][0]
        self.assertEqual(pair["mde"], 0.1458)
        self.assertEqual(pair["left_mde"], 0.05)
        self.assertEqual(pair["right_mde"], 0.20)
        self.assertEqual(pair["label"], "inside noise")

    def test_two_equally_precise_runs_are_held_to_the_mde_they_published(self) -> None:
        """The identity that makes the derivation trustworthy: when both runs report the same
        MDE, the pairwise threshold IS that MDE, which is what a per-run MDE already claims to
        mean -- the smallest difference detectable between two runs of that size."""
        runs = _synthetic(
            [_suite("accuracy", score=0.50, mde=0.12)],
            [_suite("accuracy", score=0.70, mde=0.12)],
        )
        pair = compare_runs(runs)["suites"][0]["pairs"][0]
        self.assertEqual(pair["mde"], 0.12)
        self.assertEqual(pair["label"], "distinguishable")

    def test_a_gap_below_the_threshold_is_not_called_real(self) -> None:
        runs = _synthetic(
            [_suite("accuracy", score=0.50, mde=0.12)],
            [_suite("accuracy", score=0.58, mde=0.12)],
        )
        pair = compare_runs(runs)["suites"][0]["pairs"][0]
        self.assertEqual(pair["delta"], 0.08)
        self.assertEqual(pair["label"], "inside noise")

    def test_a_different_judge_configuration_is_refused(self) -> None:
        runs = _synthetic([_suite("accuracy", score=0.9, mde=0.1)],
                          [_suite("accuracy", score=0.9, mde=0.1)])
        runs[1].report["provenance"]["judge_config_sha256"] = "a different judge"
        with self.assertRaises(CompareError) as caught:
            compare_runs(runs)
        self.assertIn("judge configuration hash differs", str(caught.exception))

    def test_one_target_is_not_a_comparison(self) -> None:
        runs = _synthetic([_suite("accuracy", score=0.9, mde=0.1)], [])
        with self.assertRaises(CompareError):
            compare_runs(runs[:1])

    def test_units_one_target_did_not_score_are_coverage_not_disagreement(self) -> None:
        """An item one target scored and another did not is missing coverage. Folding it in
        with the genuine disagreements would report an absent measurement as a difference of
        opinion."""
        runs = _synthetic(
            [_suite("accuracy", score=0.5, mde=0.1,
                    items=[{"item": "shared", "score": 1.0}, {"item": "only-a", "score": 0.0}])],
            [_suite("accuracy", score=0.5, mde=0.1,
                    items=[{"item": "shared", "score": 0.0}])],
        )
        entry = compare_runs(runs)["suites"][0]
        self.assertEqual([d["unit"] for d in entry["unit_disagreements"]], ["item:shared"])
        self.assertEqual([c["unit"] for c in entry["unit_coverage_differences"]],
                         ["item:only-a"])


if __name__ == "__main__":
    unittest.main()
