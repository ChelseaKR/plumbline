"""The prose must be held to the same evidence the published page is.

`site/index.html` is regenerated from the committed artifacts and compared
byte for byte, so it cannot drift. `README.md` and `DESIGN.md` had no such
check, and they did drift: the demo bundle grew from 174 items to 178, the
page said 178 the moment it was rebuilt, and four figures in the README went
on describing a bundle that no longer existed -- including a tolerated score
published as 0.9943 where 177 of 178 is 0.9944.

`tools/check_claims.py` closes that. This file checks the same two things
`tests/test_site.py` checks about the page: that the claims hold today, and
that the check can actually fail. A verification that cannot fail is the
vacuous pass wearing a different hat, and this one has two distinct ways of
failing that both need proving -- a figure that disagrees with the evidence,
and a sentence that has been reworded out from under its own check.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_claims  # noqa: E402


class ThePublishedFiguresMatchTheEvidence(unittest.TestCase):
    def test_every_claim_holds(self):
        self.assertEqual(
            check_claims.check(), [],
            "a published figure disagrees with the committed evidence; run "
            "`python3 tools/check_claims.py` for the list")

    def test_the_check_command_agrees(self):
        self.assertEqual(check_claims.main([]), 0)


class TheCheckCanFail(unittest.TestCase):
    """Both failure modes, proved rather than assumed."""

    def test_a_figure_that_disagrees_is_caught(self):
        # Claim the README says something the evidence does not.
        claim = check_claims.CLAIMS[0]
        wrong = check_claims.Claim(
            doc=claim.doc, what=claim.what, pattern=claim.pattern,
            expect=lambda facts: {"items": "999999"})
        problems = check_claims.check((wrong,))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("999999", problems[0])

    def test_a_sentence_that_no_longer_exists_is_caught(self):
        # The subtler failure: the claim is not wrong, it is gone, and a
        # checker that shrugged at that would report green about nothing.
        missing = check_claims.Claim(
            doc="README.md", what="a sentence nobody has written",
            pattern=r"the bundle holds (?P<items>[0-9]+) haddock",
            expect=lambda facts: {"items": facts["items"]})
        problems = check_claims.check((missing,))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not there any more", problems[0])

    def test_a_claim_stated_twice_is_caught(self):
        # Two spellings of one figure means one of them is unchecked, which
        # is how the README came to say 174 in three places at once.
        twice = check_claims.Claim(
            doc="README.md", what="a pattern that matches all over the page",
            pattern=r"(?P<n>[0-9]+) items",
            expect=lambda facts: {"n": facts["items"]})
        problems = check_claims.check((twice,))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("times", problems[0])


class TheFiguresComeFromTheEvidence(unittest.TestCase):
    """The figures are read from the artifacts, not typed into this repo."""

    def test_the_item_count_is_the_committed_report_s(self):
        import json
        report = sorted((REPO / "audits").glob("*/report.json"))[0]
        committed = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(check_claims.facts()["items"],
                         str(committed["dataset"]["items"]))

    def test_the_tolerated_score_is_the_defect_matrix_s(self):
        import json
        matrix = json.loads(
            (REPO / "proof" / "matrix.json").read_text(encoding="utf-8"))
        note = check_claims._matrix_note(matrix, "refusal-one-under-refusal")
        facts = check_claims.facts()
        self.assertIn(f"out of {facts['tolerated_items']} items scores "
                      f"{facts['tolerated_score']} and passes", note)


if __name__ == "__main__":
    unittest.main()
