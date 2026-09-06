"""`plumbline explain`: one item, across every suite that read it.

Every case here drives a real `audit` run over a real sealed bundle and then explains an item
out of the report that run wrote. Explaining a hand-written report would test the renderer
against a fixture nobody produced, and the property worth having is that the explanation
matches what the harness actually recorded.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from plumbline.cli import EXIT_INTEGRITY_REFUSAL, EXIT_PASS, EXIT_USAGE
from plumbline.explain import ExplainError, explain
from plumbline.judges import normalize, strip_citations

from helpers import answer_item, response, run_cli, write_bundle

CONFIG = """\
[target]
name = "explain-test"

[dataset]
path = "{dataset_path}"

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


def _run(root: Path, items: list[dict], responses: list[dict],
         sources: list[dict] | None = None) -> tuple[Path, Path]:
    """Seal a bundle, audit it, and return (bundle dir, report path)."""
    bundle = write_bundle(root, items, responses, sources=sources)
    config = root / "config.toml"
    config.write_text(CONFIG.format(dataset_path=bundle), encoding="utf-8")
    out = root / "audits"
    run_cli("audit", "--config", str(config), "--out", str(out))
    report = next(out.glob("*/report.json"))
    return bundle, report


#: An item whose recorded answer states a number its `expected` does not. This is the tamper
#: drill in miniature: the drill rewrites "850 dollars" to "900 dollars" in the demo dataset,
#: and the number that appears is the thread a reader follows through the suites.
PLANTED = "rent-cap"
SOURCES = [{"id": "src-rent-cap", "text": "The rent cap is 850 dollars per month."}]
ITEMS = [
    answer_item(PLANTED, "The rent cap is 850 dollars per month.",
                load_bearing=True, sources=["src-rent-cap"]),
    answer_item("clean", "The office opens at nine.", sources=["src-rent-cap"]),
]
RESPONSES = [
    response(PLANTED, "The rent cap is 900 dollars per month. [src-rent-cap]"),
    response("clean", "The office opens at nine."),
]


class ExplainTests(unittest.TestCase):
    def test_the_planted_number_appears_under_every_suite_that_saw_it(self) -> None:
        """The drill's property: the number that was planted is visible in each suite that
        read the item, not only in the one that happened to record it in a field."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, report = _run(root, ITEMS, RESPONSES, SOURCES)
            code, out, _ = run_cli("explain", str(report), PLANTED, "--bundle", str(bundle))
            self.assertEqual(code, EXIT_PASS)
            sections = {
                block.split("\n", 1)[0].strip(): block
                for block in out.split("\n## ")[1:]
            }
            for suite in ("accuracy", "groundedness"):
                self.assertIn(suite, sections, f"{suite} did not appear in the explanation")
                self.assertIn(
                    "900", sections[suite],
                    f"the planted number is not visible under {suite}; a reader asking why "
                    f"{suite} marked this item down is not being shown the answer",
                )

    def test_an_unknown_item_exits_2_rather_than_printing_an_empty_page(self) -> None:
        """A blank explanation reads as "nothing was wrong with it"."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, report = _run(root, ITEMS, RESPONSES, SOURCES)
            code, out, err = run_cli("explain", str(report), "no-such-item")
            self.assertEqual(code, EXIT_USAGE)
            self.assertEqual(out, "")
            self.assertIn("no-such-item", err)

    def test_a_passing_item_explains_why_it_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, report = _run(root, ITEMS, RESPONSES, SOURCES)
            code, out, _ = run_cli("explain", str(report), "clean", "--bundle", str(bundle))
            self.assertEqual(code, EXIT_PASS)
            self.assertIn("accuracy", out)
            self.assertIn("counted into the suite's pooled score", out)
            # It says what it scored, not merely that nothing went wrong.
            self.assertIn("Share of the suite's score", out)

    def test_output_is_byte_identical_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, report = _run(root, ITEMS, RESPONSES, SOURCES)
            first = run_cli("explain", str(report), PLANTED, "--bundle", str(bundle))[1]
            second = run_cli("explain", str(report), PLANTED, "--bundle", str(bundle))[1]
            self.assertEqual(first, second)
            first_json = run_cli("explain", str(report), PLANTED,
                                 "--bundle", str(bundle), "--json")[1]
            second_json = run_cli("explain", str(report), PLANTED,
                                  "--bundle", str(bundle), "--json")[1]
            self.assertEqual(first_json, second_json)
            json.loads(first_json)

    def test_a_bundle_the_report_did_not_come_from_is_refused(self) -> None:
        """Explaining an item against a different dataset would produce a fluent account of an
        answer this run never scored."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, report = _run(root, ITEMS, RESPONSES, SOURCES)
            other = write_bundle(
                root,
                [answer_item(PLANTED, "Something else entirely.")],
                [response(PLANTED, "Something else entirely.")],
                name="other-bundle",
            )
            code, out, err = run_cli("explain", str(report), PLANTED, "--bundle", str(other))
            self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
            self.assertEqual(out, "")
            self.assertIn("not the one the report was produced from", err)

    def test_without_a_bundle_the_missing_half_says_so(self) -> None:
        """Absence rendered as itself. The sections that need the bundle must say they are not
        being shown, never render as an empty diff or a zero."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, report = _run(root, ITEMS, RESPONSES, SOURCES)
            code, out, _ = run_cli("explain", str(report), PLANTED)
            self.assertEqual(code, EXIT_PASS)
            self.assertIn("Not shown: no bundle given", out)
            self.assertNotIn("Numbers the answer states", out)

    def test_the_diff_is_tokenised_the_way_the_score_is(self) -> None:
        """`answer_score` strips citation markers from the answer and keeps function words. A
        diff tokenised any other way is a second opinion: an earlier draft dropped stopwords
        and kept citations, and reported `src` as a word the answer had added."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, report = _run(root, ITEMS, RESPONSES, SOURCES)
            code, out, _ = run_cli("explain", str(report), PLANTED,
                                   "--bundle", str(bundle), "--json")
            self.assertEqual(code, EXIT_PASS)
            diff = json.loads(out)["bundle"]["diff"]
            self.assertIn("900", diff["added_numbers"])
            self.assertIn("850", diff["missing_numbers"])
            # Pinned to the judge's own functions rather than to a string this test guesses
            # at. An earlier version of this assertion looked for "src-rent-cap" in the added
            # tokens; `normalize` splits that marker into "src", "rent" and "cap", so the
            # string never appeared and the check passed against a diff that had leaked.
            expected_text = ITEMS[0]["expected"]
            answer_text = RESPONSES[0]["response"]
            judge_answer = set(normalize(strip_citations(answer_text)).split())
            judge_expected = set(normalize(expected_text).split())
            self.assertEqual(diff["added_tokens"], sorted(judge_answer - judge_expected))
            self.assertEqual(diff["missing_tokens"], sorted(judge_expected - judge_answer))
            self.assertNotIn(
                "src", diff["added_tokens"],
                "the citation marker leaked into the diff; the score never saw it",
            )

    def test_an_item_with_no_expected_is_not_reported_as_an_even_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                {"id": "no-expected", "lang": "en", "behavior": "refuse",
                 "prompt": "prompt for no-expected"},
                *ITEMS,
            ]
            responses = [response("no-expected", "I cannot help with that."), *RESPONSES]
            bundle, report = _run(root, items, responses, SOURCES)
            code, out, _ = run_cli("explain", str(report), "no-expected",
                                   "--bundle", str(bundle), "--json")
            self.assertEqual(code, EXIT_PASS)
            diff = json.loads(out)["bundle"]["diff"]
            self.assertFalse(diff["available"])
            self.assertIn("no `expected`", diff["reason"])
            self.assertNotIn("shared_tokens", diff)

    def test_a_share_of_the_score_is_offered_only_when_the_score_is_that_mean(self) -> None:
        """The share is derived from the suite's own records, so a suite whose score is not
        the mean of them is described as having no per-item share rather than given a made-up
        one."""
        report = {
            "provenance": {"run_id": "r", "dataset_id": "d"},
            "dataset": {"name": "n"},
            "target": "t",
            "verdict": "PASS",
            "suites": [{
                "suite": "invented",
                # 0.9 is not the mean of the records below (which is 0.5).
                "score": 0.9, "floor": 0.5, "verdict": "PASS", "n": 2,
                "hard_failures": [],
                "items": [{"item": "a", "score": 0.0}, {"item": "b", "score": 1.0}],
            }],
            "couplings": None,
        }
        explanation = explain(report, "a")
        view = explanation["suites"][0]
        self.assertIsNone(view["contribution"])
        self.assertIn("not the mean", view["contribution_note"])

    def test_an_item_named_only_in_a_compared_pair_is_still_found(self) -> None:
        """`cross_language` scores a pair and keys the record by `pair`, not `item`. An item
        reachable only that way must still be explainable, or the suite that most often
        produces a puzzling red row is the one the verb cannot open."""
        report = {
            "provenance": {"run_id": "r", "dataset_id": "d"},
            "dataset": {"name": "n"},
            "target": "t",
            "verdict": "FAIL",
            "suites": [{
                "suite": "cross_language",
                "score": 0.0, "floor": 1.0, "verdict": "FAIL", "n": 1,
                "hard_failures": ["left"],
                "items": [{"pair": ["left", "right"], "score": 0.0,
                           "numbers": {"en": ["900"], "es": ["850"]}}],
            }],
            "couplings": None,
        }
        explanation = explain(report, "left")
        self.assertEqual(explanation["suites"][0]["matched_on"], "pair")
        self.assertTrue(explanation["suites"][0]["hard_failure"])
        with self.assertRaises(ExplainError):
            explain(report, "neither")


if __name__ == "__main__":
    unittest.main()
