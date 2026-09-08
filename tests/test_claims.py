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

import contextlib
import io
import re
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


class TheGateStatesItsOwnCoverage(unittest.TestCase):
    """`8 published figures match the evidence` was true and not a share.

    It said nothing about how much of the two documents those eight figures
    covered, and the answer was 15 numerals out of 490. A green line that does
    not carry its own denominator reads exactly like one that examined
    everything -- which is the defect this repository exists to argue against,
    in the file that argues it.
    """

    def test_every_gated_document_reports_both_numbers(self):
        census = check_claims.coverage()
        self.assertEqual(set(census), set(check_claims.GATED_DOCUMENTS))
        for doc, (bound, total) in census.items():
            self.assertGreater(total, 0, doc)
            self.assertGreater(bound, 0, doc)
            self.assertLessEqual(bound, total, doc)

    def test_the_numerator_counts_what_the_claims_actually_capture(self):
        # Not a separate count that could drift from the claims: every bound
        # figure is a group some claim matched, tokenised the same way the
        # denominator is.
        texts = {doc: check_claims._read(doc)
                 for doc in check_claims.GATED_DOCUMENTS}
        expected = {doc: 0 for doc in texts}
        for claim in check_claims.CLAIMS:
            found = list(re.finditer(claim.pattern, texts[claim.doc]))
            self.assertEqual(len(found), 1, claim.what)
            for value in found[0].groupdict().values():
                if check_claims.NUMERAL.fullmatch(value or ""):
                    expected[claim.doc] += 1
        self.assertEqual({d: b for d, (b, _) in
                          check_claims.coverage(texts=texts).items()},
                         expected)

    def test_the_command_prints_the_share_it_examined(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check_claims.main([]), 0)
        printed = out.getvalue()
        census = check_claims.coverage()
        bound = sum(b for b, _ in census.values())
        total = sum(t for _, t in census.values())
        self.assertIn(f"{bound} of {total} numerals", printed)
        for doc, (b, t) in census.items():
            self.assertIn(f"{doc} {b} of {t}", printed)

    def test_the_share_is_not_the_whole_document(self):
        # If this ever stops being true the sentence about unchecked prose is
        # wrong and has to go, which is the point of asserting it.
        census = check_claims.coverage()
        self.assertLess(sum(b for b, _ in census.values()),
                        sum(t for _, t in census.values()))


class TheUniverseCannotShrinkInSilence(unittest.TestCase):
    """Four floors, each proved to refuse. None of them is a counter."""

    def test_a_claim_in_an_undeclared_document_is_refused(self):
        stray = check_claims.Claim(
            doc="CHANGELOG.md", what="a figure in a document nobody declared",
            pattern=r"(?P<n>[0-9]+)",
            expect=lambda facts: {"n": facts["items"]})
        with self.assertRaises(check_claims.Stale) as caught:
            check_claims.refuse_a_universe_that_cannot_fail((stray,))
        self.assertIn("CHANGELOG.md", str(caught.exception))

    def test_a_declared_document_with_nothing_anchored_is_refused(self):
        readme_only = tuple(c for c in check_claims.CLAIMS
                            if c.doc == "README.md")
        self.assertTrue(readme_only)
        with self.assertRaises(check_claims.Stale) as caught:
            check_claims.refuse_a_universe_that_cannot_fail(readme_only)
        self.assertIn("DESIGN.md", str(caught.exception))

    def test_a_claim_that_captures_no_figure_is_refused(self):
        # Synthetic documents, so the claim under test is the only one that
        # matches: a claim whose pattern does not match exactly once is a
        # different failure, reported by `check`, and this refusal must not be
        # reached through it.
        wordless = check_claims.Claim(
            doc="README.md", what="a claim that binds nothing",
            pattern=r"(?P<what>a sentence with no figure in it)",
            expect=lambda facts: {"what": "a sentence with no figure in it"})
        texts = {"README.md": "a sentence with no figure in it",
                 "DESIGN.md": "the bundle holds 178 items"}
        with self.assertRaises(check_claims.Stale) as caught:
            check_claims.refuse_a_universe_that_cannot_fail((wordless,), texts)
        self.assertIn("captures no figure", str(caught.exception))

    def test_a_document_the_scan_reads_as_empty_is_refused(self):
        texts = {doc: check_claims._read(doc)
                 for doc in check_claims.GATED_DOCUMENTS}
        texts["DESIGN.md"] = "a design record with no figures in it at all"
        with self.assertRaises(check_claims.Stale) as caught:
            check_claims.refuse_a_universe_that_cannot_fail(
                check_claims.CLAIMS, texts)
        self.assertIn("DESIGN.md", str(caught.exception))

    def test_the_shipped_universe_passes_all_four(self):
        check_claims.refuse_a_universe_that_cannot_fail()


if __name__ == "__main__":
    unittest.main()
