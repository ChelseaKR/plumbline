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
        # figure is a group some claim matched, tokenized the same way the
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
        live = check_claims.live_coverage()
        bound = sum(b for b, _, _ in live.values())
        live_total = sum(lt for _, lt, _ in live.values())
        self.assertIn(f"{bound} of {live_total} numerals", printed)
        for doc, (b, lt, d) in live.items():
            self.assertIn(f"{doc} {b} of {lt} live, {d} dated", printed)

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


class ARestatementIsHeldToTheSameEvidence(unittest.TestCase):
    """A claim anchors one sentence. These two hold every other mention.

    Both were written because both were live on 2026-09-08: `DESIGN.md` said
    `174 items` six times against a 178-item bundle, and its suite inventory
    named fourteen of the fifteen suites the report scores. Neither carries a
    number a human maintains -- the bundle size and the suite ids are read
    from the committed artifacts -- which is the reason they are not six more
    `Claim` rows.
    """

    def test_a_stale_restatement_is_caught(self):
        texts = {"DESIGN.md": "## Demo dataset\n\nAt 174 items the suites agree.\n",
                 "README.md": "## Releases\n\nThe bundle holds 178 items.\n"}
        with self.assertRaises(check_claims.Stale) as caught:
            check_claims.restated_bundle_size(texts, size=178)
        self.assertIn("174 items", str(caught.exception))

    def test_a_figure_under_a_dated_heading_is_left_alone(self):
        texts = {"DESIGN.md": ("## Acceptance record (verified at M9)\n\n"
                               "Scored 174 items and exited 0.\n"),
                 "README.md": "## Releases\n\nThe bundle holds 178 items.\n"}
        checked, dated, _exempt = check_claims.restated_bundle_size(
            texts, size=178)
        self.assertEqual((checked, dated), (1, 1))

    def test_a_scan_that_reads_nothing_is_refused(self):
        # The floor. A reader that stopped matching reports the same clean
        # line as one that read every document.
        texts = {"DESIGN.md": "## Suites\n\nno figures here\n",
                 "README.md": "## Releases\n\nnone here either\n"}
        with self.assertRaises(check_claims.Stale) as caught:
            check_claims.restated_bundle_size(texts, size=178)
        self.assertIn("stopped matching", str(caught.exception))

    def test_an_exemption_nobody_needs_is_refused(self):
        # Self-limiting, and scoped to the shipped documents. A synthetic call
        # never contains the exemptions, so enforcing it there would make
        # every other test in this class fail for the wrong reason -- the same
        # `claims is CLAIMS` distinction the four universe refusals draw.
        original = check_claims.EXEMPT_ITEM_PHRASES
        check_claims.EXEMPT_ITEM_PHRASES = original + (
            ("a sentence this repository does not contain", "invented"),)
        try:
            with self.assertRaises(check_claims.Stale) as caught:
                check_claims.restated_bundle_size()
            self.assertIn("appear", str(caught.exception))
        finally:
            check_claims.EXEMPT_ITEM_PHRASES = original
        check_claims.restated_bundle_size()

    def test_a_suite_missing_from_the_inventory_is_named(self):
        text = "# Title\n\n## Suites\n\n`smoke` and `accuracy`.\n"
        missing, total = check_claims.suites_missing_from_the_inventory(
            text, names=["smoke", "accuracy", "refusal"])
        self.assertEqual((missing, total), (["refusal"], 3))

    def test_naming_a_suite_outside_the_inventory_does_not_count(self):
        # The reason this is scoped to a section and not to the file: the
        # roadmap table names every suite in passing, so a whole-document
        # membership test passes over an inventory missing one.
        text = ("# Title\n\n## Suites\n\n`smoke`.\n\n"
                "## Roadmap\n\n`refusal` shipped at M2.\n")
        missing, _total = check_claims.suites_missing_from_the_inventory(
            text, names=["smoke", "refusal"])
        self.assertEqual(missing, ["refusal"])

    def test_an_empty_suite_list_is_refused(self):
        with self.assertRaises(check_claims.Stale):
            check_claims.suites_missing_from_the_inventory(
                "# T\n\n## Suites\n\nx\n", names=[])

    def test_the_shipped_tree_passes_both(self):
        check_claims.restated_bundle_size()
        missing, total = check_claims.suites_missing_from_the_inventory()
        self.assertEqual(missing, [])
        self.assertGreaterEqual(total, 15)


if __name__ == "__main__":
    unittest.main()


class TheDenominatorIsTheOneAGateCouldReach(unittest.TestCase):
    """`29 of 490` is a share of a number no gate is allowed to cover.

    171 of `DESIGN.md`'s 297 numerals sit under a heading that dates itself.
    Those are records of what was observed then, and a claim anchored in one
    would rewrite the archive every time the evidence moved. Publishing them
    inside the denominator makes the gate look four times more absent than it
    is, and hides which numerals are actually unchecked.
    """

    def test_the_three_numbers_partition_the_document(self):
        whole = check_claims.coverage()
        live = check_claims.live_coverage()
        self.assertEqual(set(live), set(check_claims.GATED_DOCUMENTS))
        for doc, (bound, live_total, dated) in live.items():
            self.assertEqual(live_total + dated, whole[doc][1], doc)
            self.assertEqual(bound, whole[doc][0], doc)
            self.assertLessEqual(bound, live_total, doc)

    def test_a_document_with_history_in_it_reports_some(self):
        # If this ever reads zero the distinction has stopped being measured
        # and the honest line above is decoration.
        _, live_total, dated = check_claims.live_coverage()["DESIGN.md"]
        self.assertGreater(dated, 0)
        self.assertGreater(live_total, 0)

    def test_the_command_prints_both_denominators(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check_claims.main([]), 0)
        printed = out.getvalue()
        live = check_claims.live_coverage()
        bound = sum(b for b, _, _ in live.values())
        live_total = sum(lt for _, lt, _ in live.values())
        dated = sum(d for _, _, d in live.values())
        self.assertIn(f"{bound} of {live_total} numerals in the live prose",
                      printed)
        self.assertIn(f"{dated} more sit under headings that date themselves",
                      printed)
        self.assertIn(f"{live_total + dated} numerals in all", printed)


class AClaimMayNotBeAnchoredInHistory(unittest.TestCase):
    """The refusal that keeps the archive an archive."""

    def test_a_claim_pinned_to_a_dated_sentence_is_refused(self):
        # `## Acceptance record (verified at M9, clean checkout)` really does
        # say `174 items`, and it must go on saying it.
        historical = check_claims.Claim(
            doc="DESIGN.md",
            what="a figure inside the acceptance record",
            pattern=r"Across (?P<items>174) items the planted fabrication",
            expect=lambda facts: {"items": facts["items"]})
        self.assertEqual(
            check_claims.claims_anchored_only_in_history((historical,)),
            ["a figure inside the acceptance record"])
        # Paired with a live README claim so the refusal under test is the one
        # that fires, rather than the earlier "nothing anchored here" floor.
        universe = (check_claims.CLAIMS[0], historical)
        with self.assertRaises(check_claims.Stale) as caught:
            check_claims.refuse_a_universe_that_cannot_fail(universe)
        self.assertIn("date", str(caught.exception))

    def test_no_shipped_claim_is_anchored_in_history(self):
        self.assertEqual(check_claims.claims_anchored_only_in_history(), [])


class ATolerancveIsDerivedNotWrittenDown(unittest.TestCase):
    def test_the_tolerance_is_the_floor_over_the_population(self):
        # 178 items at a floor of 0.90: 161 successes score 0.9045 and pass,
        # 160 score 0.8989 and do not, so seventeen may be wrong.
        self.assertEqual(check_claims._tolerated(178, 0.90), 17)
        self.assertEqual(check_claims._tolerated(178, 1.00), 0)

    def test_a_tolerance_over_an_empty_population_is_refused(self):
        # The whole defect class in one line: `(0 - 0) / 0` has no answer, and
        # a suite that scored nothing tolerates nothing, not everything.
        with self.assertRaises(check_claims.Stale):
            check_claims._tolerated(0, 0.90)


class SpelledFiguresAreHeldToo(unittest.TestCase):
    """`NUMERAL` cannot see a figure written as a word, and two went stale there.

    On 2026-09-13 the README said `Twenty-one cases` of a 23-case matrix and
    `DESIGN.md` said `Thirteen suites reporting PASS` of a fifteen-suite report,
    while `29 of 319 numerals` printed green above both.
    """

    def test_compound_figures_are_spelled_and_seen_as_one(self):
        self.assertEqual(check_claims._spell(23), "twenty-three")
        self.assertEqual(check_claims._spell(40), "forty")
        self.assertEqual(check_claims._spell(19), "nineteen")
        with self.assertRaises(check_claims.Stale):
            check_claims._spell(100)
        words = check_claims.NUMBER_WORD.findall(
            "Twenty-three cases, all fifteen suites, one refusal, twenty-three")
        self.assertEqual(words, ["Twenty-three", "fifteen", "one", "twenty-three"])

    def test_the_census_partitions_each_document(self):
        for doc, (bound, live, dated) in check_claims.spelled_coverage().items():
            whole = len(check_claims.NUMBER_WORD.findall(check_claims._read(doc)))
            self.assertEqual(live + dated, whole, doc)
            self.assertLessEqual(bound, live, doc)
        self.assertGreater(
            sum(b for b, _, _ in check_claims.spelled_coverage().values()), 0)

    def test_the_command_prints_the_spelled_share(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check_claims.main([]), 0)
        spelled = check_claims.spelled_coverage()
        bound = sum(b for b, _, _ in spelled.values())
        live = sum(lt for _, lt, _ in spelled.values())
        self.assertIn(f"spelled: {bound} of {live} number-words in the live prose",
                      out.getvalue())

    def test_a_stale_spelled_figure_is_caught(self):
        claim = next(c for c in check_claims.CLAIMS
                     if c.what == "what the defect-injection matrix contains")
        wrong = check_claims.Claim(
            doc=claim.doc, what=claim.what, pattern=claim.pattern,
            expect=lambda facts: {**claim.expect(facts), "cases": "Twenty-one"})
        problems = check_claims.check((wrong,))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("'Twenty-one'", problems[0])


class TheMatrixFiguresRefuseASentenceTheyCannotFill(unittest.TestCase):
    MATRIX = {"cases": [{"expect": "suite_failure"}, {"expect": "integrity_refusal"},
                        {"expect": "configuration_error"}],
              "suites_with_a_defect_case": ["a", "b"],
              "suites_without_a_defect_case": []}
    REPORT = {"suites": [{"suite": "a", "verdict": "PASS"},
                         {"suite": "b", "verdict": "PASS"}]}

    def test_the_figures_come_from_the_rows(self):
        figures = check_claims._matrix_figures(self.MATRIX, self.REPORT)
        self.assertEqual(figures["matrix_cases_sentence_start"], "Three")
        self.assertEqual(figures["matrix_suites_proved"], "two")
        self.assertEqual(figures["matrix_integrity_refusals"], "one")
        self.assertEqual(figures["matrix_configuration_errors"], "one")
        self.assertEqual(figures["suites_passing_sentence_start"], "Two")

    def test_an_uncovered_suite_is_not_all_suites_covered(self):
        matrix = {**self.MATRIX, "suites_without_a_defect_case": ["c"]}
        with self.assertRaises(check_claims.Stale):
            check_claims._matrix_figures(matrix, self.REPORT)

    def test_a_failing_suite_is_not_a_clean_bundle(self):
        report = {"suites": [{"suite": "a", "verdict": "PASS"},
                             {"suite": "b", "verdict": "FAIL"}]}
        with self.assertRaises(check_claims.Stale):
            check_claims._matrix_figures(self.MATRIX, report)

    def test_an_empty_matrix_or_report_counts_nothing(self):
        with self.assertRaises(check_claims.Stale):
            check_claims._matrix_figures({**self.MATRIX, "cases": []}, self.REPORT)
        with self.assertRaises(check_claims.Stale):
            check_claims._matrix_figures(self.MATRIX, {"suites": []})
