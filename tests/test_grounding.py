"""Groundedness, citation validity, citation accuracy."""

import tempfile
import unittest
from pathlib import Path

from plumbline.bundle import BundleError, load
from plumbline.judges import LexicalJudge
from plumbline.suites import FAIL, PASS, EmptyPopulationError, get as get_suite

from helpers import answer_item, response, write_bundle

CAP_TEXT = ("Riverbend Rent Relief pays a maximum payment of 850 dollars "
            "per month toward rent.")
HOURS_TEXT = ("The benefits office accepts walk-ins Monday through Friday "
              "from 9 to 4.")

SOURCES = [
    {"id": "src-cap", "title": "Payment cap", "text": CAP_TEXT},
    {"id": "src-hours", "title": "Office hours", "text": HOURS_TEXT},
]


class GroundingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.judge = LexicalJudge()
        self._counter = 0

    def bundle(self, items, responses, sources=SOURCES):
        self._counter += 1
        return load(write_bundle(
            self.root, items, responses, sources=sources,
            name=f"fixture-{self._counter}",
        ))


class BundleSourceTests(GroundingTestCase):
    def test_sources_are_loaded_and_addressable(self):
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars per month",
                         sources=["src-cap"])],
            [response("a1", "the maximum payment is 850 dollars per month "
                            "[src-cap]")],
        )
        self.assertEqual(bundle.source("src-cap").title, "Payment cap")
        self.assertEqual(bundle.source_text_for(bundle.items[0]), CAP_TEXT)

    def test_item_pointing_at_a_missing_source_is_a_bundle_error(self):
        with self.assertRaises(BundleError):
            self.bundle(
                [answer_item("a1", "x", sources=["src-ghost"])],
                [response("a1", "x [src-ghost]")],
            )


class GroundednessTests(GroundingTestCase):
    def test_supported_answer_scores_high(self):
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars per month",
                         sources=["src-cap"])],
            [response("a1", "The maximum payment is 850 dollars per month. "
                            "[src-cap]")],
        )
        result = get_suite("groundedness").evaluate(bundle, self.judge, 0.70)
        self.assertEqual(result.verdict, PASS)
        self.assertGreater(result.score, 0.9)

    def test_invented_number_is_caught_even_when_the_prose_matches(self):
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars per month",
                         sources=["src-cap"])],
            [response("a1", "The maximum payment is 1200 dollars per month. "
                            "[src-cap]")],
        )
        result = get_suite("groundedness").evaluate(bundle, self.judge, 0.70)
        self.assertEqual(result.item_records[0]["unsupported_numbers"], ["1200"])
        self.assertEqual(result.item_records[0]["number_support"], 0.0)
        self.assertEqual(result.score, 0.0)  # weaker channel wins
        self.assertEqual(result.verdict, FAIL)

    def test_load_bearing_invention_is_a_hard_failure_above_the_floor(self):
        items, responses = [], []
        for i in range(9):
            items.append(answer_item(f"ok{i}", "walk-ins Monday through Friday",
                                     sources=["src-hours"]))
            responses.append(response(f"ok{i}",
                                      "Walk-ins Monday through Friday. [src-hours]"))
        items.append(answer_item("lb", "the maximum payment is 850 dollars",
                                 sources=["src-cap"], load_bearing=True))
        responses.append(response("lb", "The maximum payment is 1200 dollars. "
                                        "[src-cap]"))
        bundle = self.bundle(items, responses)
        result = get_suite("groundedness").evaluate(bundle, self.judge, 0.70)
        self.assertGreater(result.score, result.floor)
        self.assertEqual(result.verdict, FAIL)
        self.assertEqual(result.hard_failures, ["lb"])

    def test_unsourced_answers_are_named_not_hidden(self):
        bundle = self.bundle(
            [answer_item("a1", "walk-ins Monday through Friday",
                         sources=["src-hours"]),
             answer_item("a2", "something with no sources")],
            [response("a1", "Walk-ins Monday through Friday. [src-hours]"),
             response("a2", "Something with no sources.")],
        )
        result = get_suite("groundedness").evaluate(bundle, self.judge, 0.70)
        self.assertEqual(result.n, 1)
        self.assertEqual(result.details["items_without_sources"], ["a2"])

    def test_no_sourced_answers_is_an_error(self):
        bundle = self.bundle([answer_item("a1", "x")], [response("a1", "x")])
        with self.assertRaises(EmptyPopulationError):
            get_suite("groundedness").evaluate(bundle, self.judge, 0.70)


class CitationValidityTests(GroundingTestCase):
    def test_resolving_citation_passes(self):
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars",
                         sources=["src-cap"])],
            [response("a1", "The maximum payment is 850 dollars. [src-cap]")],
        )
        result = get_suite("citation_validity").evaluate(bundle, self.judge, 0.95)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.verdict, PASS)

    def test_fabricated_citation_is_a_hard_failure(self):
        items, responses = [], []
        for i in range(9):
            items.append(answer_item(f"ok{i}", "walk-ins Monday through Friday",
                                     sources=["src-hours"]))
            responses.append(response(f"ok{i}",
                                      "Walk-ins Monday through Friday. [src-hours]"))
        items.append(answer_item("bad", "the maximum payment is 850 dollars",
                                 sources=["src-cap"]))
        responses.append(response("bad", "The maximum payment is 850 dollars. "
                                         "[src-invented-2024]"))
        bundle = self.bundle(items, responses)
        result = get_suite("citation_validity").evaluate(bundle, self.judge, 0.95)
        self.assertEqual(result.verdict, FAIL)
        self.assertEqual(result.hard_failures, ["bad"])
        record = next(r for r in result.item_records if r["item"] == "bad")
        self.assertEqual(record["fabricated_citations"], ["src-invented-2024"])

    def test_uncited_answer_scores_zero(self):
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars",
                         sources=["src-cap"])],
            [response("a1", "The maximum payment is 850 dollars.")],
        )
        result = get_suite("citation_validity").evaluate(bundle, self.judge, 0.95)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.verdict, FAIL)
        self.assertEqual(result.hard_failures, [])  # missing, not invented

    def test_citation_outside_the_retrieved_set_is_valid_but_flagged(self):
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars",
                         sources=["src-cap"])],
            [response("a1", "The maximum payment is 850 dollars. "
                            "[src-cap] [src-hours]")],
        )
        result = get_suite("citation_validity").evaluate(bundle, self.judge, 0.95)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.item_records[0]["out_of_context_citations"],
                         ["src-hours"])


class CitationAccuracyTests(GroundingTestCase):
    def test_answer_pointing_at_the_right_source_passes(self):
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars per month",
                         sources=["src-cap"])],
            [response("a1", "The maximum payment is 850 dollars per month. "
                            "[src-cap]")],
        )
        result = get_suite("citation_accuracy").evaluate(bundle, self.judge, 0.80)
        self.assertEqual(result.verdict, PASS)

    def test_grounded_answer_pointing_at_the_wrong_source_fails(self):
        # Everything the answer says is true and is in the corpus, but the
        # citation sends the reader to the office-hours passage.
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars per month",
                         sources=["src-cap", "src-hours"])],
            [response("a1", "The maximum payment is 850 dollars per month. "
                            "[src-hours]")],
        )
        grounded = get_suite("groundedness").evaluate(bundle, self.judge, 0.70)
        self.assertEqual(grounded.verdict, PASS)  # the corpus does support it
        result = get_suite("citation_accuracy").evaluate(bundle, self.judge, 0.80)
        self.assertEqual(result.verdict, FAIL)
        self.assertEqual(result.item_records[0]["unsupported_numbers"], ["850"])

    def test_answers_citing_nothing_are_named_and_left_to_validity(self):
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars per month",
                         sources=["src-cap"]),
             answer_item("a2", "walk-ins Monday through Friday",
                         sources=["src-hours"])],
            [response("a1", "The maximum payment is 850 dollars per month. "
                            "[src-cap]"),
             response("a2", "Walk-ins Monday through Friday.")],
        )
        result = get_suite("citation_accuracy").evaluate(bundle, self.judge, 0.80)
        self.assertEqual(result.n, 1)
        self.assertEqual(result.details["answers_citing_nothing_resolvable"],
                         ["a2"])

    def test_nothing_cited_at_all_is_an_error(self):
        bundle = self.bundle(
            [answer_item("a1", "walk-ins Monday through Friday",
                         sources=["src-hours"])],
            [response("a1", "Walk-ins Monday through Friday.")],
        )
        with self.assertRaises(EmptyPopulationError):
            get_suite("citation_accuracy").evaluate(bundle, self.judge, 0.80)


class CitationStrippingTests(GroundingTestCase):
    def test_markers_do_not_leak_into_accuracy_scoring(self):
        bundle = self.bundle(
            [answer_item("a1", "the maximum payment is 850 dollars per month",
                         sources=["src-cap"])],
            [response("a1", "The maximum payment is 850 dollars per month. "
                            "[src-cap]")],
        )
        result = get_suite("accuracy").evaluate(bundle, self.judge, 0.75)
        self.assertEqual(result.score, 1.0)


if __name__ == "__main__":
    unittest.main()
