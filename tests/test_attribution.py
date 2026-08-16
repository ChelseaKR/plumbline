"""The passage-attribution suite, and the gap it exists to close.

The first test in this file is the negative control the whole suite is for: a
bundle carrying the consumer's defect — a correct-looking, sourced,
non-refused answer composed from the wrong paragraph of the right document —
on which every other grounding suite passes and `accuracy` absorbs the item
into its pooled mean. It was watched failing before the suite existed and it
is what proves the suite is measuring something no other suite measures.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plumbline.bundle import load
from plumbline.judges import LexicalJudge
from plumbline.suites import (
    FAIL,
    PASS,
    UNVERIFIABLE,
    EmptyPopulationError,
    get as get_suite,
)
from plumbline.suites.attribution import DECISION_MARGIN

from helpers import answer_item, response, write_bundle

ELIGIBILITY = ("Eligibility for the household program depends on monthly "
               "household income before deductions.")
FARE = ("The household fare discount costs 2 dollars per ride for every "
        "household rider.")

SOURCES = [
    {"id": "s-eligibility", "title": "Who qualifies", "text": ELIGIBILITY},
    {"id": "s-fare", "title": "Fare discount", "text": FARE},
]

RIGHT_PARAGRAPH = ("Eligibility depends on monthly household income before "
                   "deductions. [s-eligibility]")
WRONG_PARAGRAPH = ("The household fare discount costs 2 dollars per ride. "
                   "[s-fare]")


def _item(item_id: str, **extra) -> dict:
    return answer_item(
        item_id,
        "Eligibility depends on monthly household income before deductions.",
        sources=["s-eligibility", "s-fare"],
        answering_sources=["s-eligibility"],
        **extra,
    )


class AttributionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.judge = LexicalJudge()

    def bundle(self, items, responses, *, name="attr-bundle"):
        return load(write_bundle(self.root, items, responses, name=name,
                                 sources=SOURCES))

    def run_suite(self, suite_id, bundle, floor):
        return get_suite(suite_id).evaluate(bundle, self.judge, floor)

    def record_for(self, result, item_id):
        for record in result.item_records:
            if record["item"] == item_id:
                return record
        raise AssertionError(f"no record for {item_id}: {result.item_records}")


class TheConsumersDefect(AttributionTestCase):
    """One answer in eight is composed from the fare paragraph. The question
    asked about eligibility."""

    def setUp(self):
        super().setUp()
        items = [_item(f"q{n}") for n in range(8)]
        responses = [response(f"q{n}", RIGHT_PARAGRAPH) for n in range(1, 8)]
        responses.insert(0, response("q0", WRONG_PARAGRAPH))
        self.evidence = self.bundle(items, responses)

    def test_every_grounding_suite_passes_it(self):
        # This is the consumer's report, reproduced: grounded, cited, and the
        # citation supports the claim, because the answer really did come from
        # that passage. Nothing here is lying; the suites are answering
        # narrower questions than a reader thinks.
        for suite_id, floor in (("groundedness", 0.70),
                                ("citation_validity", 0.95),
                                ("citation_accuracy", 0.80)):
            result = self.run_suite(suite_id, self.evidence, floor)
            self.assertEqual(result.verdict, PASS,
                             f"{suite_id} scored {result.score}")

    def test_accuracy_absorbs_it_into_the_pooled_mean(self):
        result = self.run_suite("accuracy", self.evidence, 0.75)
        self.assertEqual(result.verdict, PASS)
        self.assertGreater(result.score, 0.75)
        # It is not that accuracy saw nothing — it is that what it saw cannot
        # be told apart from a paraphrase, and the mean forgives it.
        self.assertLess(self.record_for(result, "q0")["score"], 0.5)

    def test_passage_attribution_catches_it(self):
        result = self.run_suite("passage_attribution", self.evidence, 0.95)
        self.assertEqual(result.verdict, FAIL)
        self.assertEqual(result.details["misattributed_items"], ["q0"])
        record = self.record_for(result, "q0")
        self.assertEqual(record["verdict"], FAIL)
        self.assertEqual(record["best_other_source"], "s-fare")
        self.assertIn("right document, wrong paragraph", record["note"])

    def test_a_clean_bundle_passes(self):
        clean = self.bundle(
            [_item(f"q{n}") for n in range(8)],
            [response(f"q{n}", RIGHT_PARAGRAPH) for n in range(8)],
            name="clean")
        result = self.run_suite("passage_attribution", clean, 0.95)
        self.assertEqual(result.verdict, PASS)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.n, 8)


class WhatItRefusesToScore(AttributionTestCase):
    def test_an_item_that_declares_nothing_is_unverifiable_not_a_pass(self):
        items = [_item("declared"),
                 answer_item("silent", "Eligibility depends on income.",
                             sources=["s-eligibility", "s-fare"])]
        evidence = self.bundle(items, [response("declared", RIGHT_PARAGRAPH),
                                       response("silent", WRONG_PARAGRAPH)])
        result = self.run_suite("passage_attribution", evidence, 0.95)
        self.assertEqual(result.n, 1)  # not 2: the silent item is not a pass
        block = result.details["unverifiable"]
        self.assertEqual(block["reasons"]["no_declaration"], ["silent"])
        self.assertEqual(block["eligible"], 2)
        self.assertEqual(block["scored"], 1)
        self.assertNotIn("silent", [r["item"] for r in result.item_records])

    def test_no_declaration_anywhere_is_a_configuration_error(self):
        items = [answer_item("q0", "Eligibility depends on income.",
                             sources=["s-eligibility", "s-fare"])]
        evidence = self.bundle(items, [response("q0", RIGHT_PARAGRAPH)])
        with self.assertRaises(EmptyPopulationError) as caught:
            self.run_suite("passage_attribution", evidence, 0.95)
        self.assertIn("no item declares `answering_sources`",
                      str(caught.exception))

    def test_an_item_with_no_distractor_is_unverifiable(self):
        items = [answer_item("only", "Eligibility depends on income.",
                             sources=["s-eligibility"],
                             answering_sources=["s-eligibility"]),
                 _item("q1")]
        evidence = self.bundle(items, [response("only", RIGHT_PARAGRAPH),
                                       response("q1", RIGHT_PARAGRAPH)])
        result = self.run_suite("passage_attribution", evidence, 0.95)
        record = self.record_for(result, "only")
        self.assertEqual(record["verdict"], UNVERIFIABLE)
        self.assertEqual(record["reason"], "no_distractor")
        self.assertNotIn("score", record)
        self.assertEqual(result.n, 1)

    def test_every_declared_item_unverifiable_is_a_configuration_error(self):
        # The vacuous pass this suite exists to refuse: declarations present,
        # nothing checkable, and a score over nothing would still be 1.00.
        items = [answer_item("only", "Eligibility depends on income.",
                             sources=["s-eligibility"],
                             answering_sources=["s-eligibility"])]
        evidence = self.bundle(items, [response("only", RIGHT_PARAGRAPH)])
        with self.assertRaises(EmptyPopulationError) as caught:
            self.run_suite("passage_attribution", evidence, 0.95)
        self.assertIn("nothing this suite could score", str(caught.exception))

    def test_two_passages_within_the_margin_are_indistinguishable(self):
        near = [{"id": "s-a", "text": "Applications close on March 31 at 5 pm."},
                {"id": "s-b", "text": "Applications close on March 31 at 5 pm "
                                      "in every office."}]
        items = [answer_item("q0", "Applications close on March 31.",
                             sources=["s-a", "s-b"],
                             answering_sources=["s-a"]),
                 answer_item("q1", "Applications close on March 31.",
                             sources=["s-a", "s-b"],
                             answering_sources=["s-a"])]
        evidence = load(write_bundle(
            self.root, items,
            [response("q0", "Applications close on March 31 at 5 pm. [s-a]"),
             response("q1", "Applications close on March 31 at 5 pm. [s-a]")],
            name="near", sources=near))
        with self.assertRaises(EmptyPopulationError):
            self.run_suite("passage_attribution", evidence, 0.95)

    def test_the_margin_band_is_reported_per_item(self):
        near = [{"id": "s-a", "text": "Applications close on March 31 at 5 pm."},
                {"id": "s-b", "text": "Applications close on March 31 at 5 pm "
                                      "in every office."}]
        items = [answer_item("close", "Applications close on March 31.",
                             sources=["s-a", "s-b"],
                             answering_sources=["s-a"]),
                 answer_item("clear", "Eligibility depends on income.",
                             sources=["s-a", "s-b"],
                             answering_sources=["s-b"])]
        evidence = load(write_bundle(
            self.root, items,
            [response("close", "Applications close on March 31 at 5 pm. [s-a]"),
             response("clear", "Applications close in every office. [s-b]")],
            name="mixed", sources=near))
        result = self.run_suite("passage_attribution", evidence, 0.5)
        record = self.record_for(result, "close")
        self.assertEqual(record["reason"], "indistinguishable")
        self.assertLess(abs(record["margin"]), DECISION_MARGIN)
        self.assertEqual(result.details["unverifiable"]["reasons"],
                         {"indistinguishable": ["close"]})


class SeverityAndRetrieval(AttributionTestCase):
    def test_a_load_bearing_misattribution_fails_regardless_of_the_mean(self):
        items = [_item(f"q{n}") for n in range(19)]
        items.append(_item("policy", load_bearing=True))
        responses = [response(f"q{n}", RIGHT_PARAGRAPH) for n in range(19)]
        responses.append(response("policy", WRONG_PARAGRAPH))
        evidence = self.bundle(items, responses, name="load-bearing")
        result = self.run_suite("passage_attribution", evidence, 0.90)
        self.assertGreater(result.score, 0.90)  # the pooled mean forgives it
        self.assertEqual(result.verdict, FAIL)  # the severity rule does not
        self.assertEqual(result.hard_failures, ["policy"])

    def test_an_answering_passage_that_was_never_retrieved_is_named(self):
        items = [answer_item("q0", "Eligibility depends on income.",
                             sources=["s-fare"],
                             answering_sources=["s-eligibility"])]
        evidence = self.bundle(items, [response("q0", WRONG_PARAGRAPH)],
                               name="not-retrieved")
        result = self.run_suite("passage_attribution", evidence, 0.95)
        self.assertEqual(result.verdict, FAIL)
        self.assertEqual(result.details["answering_passage_not_available"],
                         ["q0"])
        self.assertIn("retrieval failure",
                      self.record_for(result, "q0")["retrieval_note"])

    def test_an_answer_from_the_right_passage_citing_another_is_noted(self):
        evidence = self.bundle(
            [_item("q0")],
            [response("q0", "Eligibility depends on monthly household income "
                            "before deductions. [s-fare]")],
            name="miscited")
        result = self.run_suite("passage_attribution", evidence, 0.95)
        self.assertEqual(result.verdict, PASS)
        self.assertIn("points the reader at a different one",
                      self.record_for(result, "q0")["note"])


class SuggestionsAreNotDeclarations(AttributionTestCase):
    def test_an_undeclared_item_gets_a_suggestion_from_its_reference_answer(self):
        items = [_item("declared"),
                 answer_item("silent", ELIGIBILITY,
                             sources=["s-eligibility", "s-fare"])]
        evidence = self.bundle(items, [response("declared", RIGHT_PARAGRAPH),
                                       response("silent", WRONG_PARAGRAPH)])
        result = self.run_suite("passage_attribution", evidence, 0.95)
        self.assertEqual(result.details["suggested_declarations"],
                         {"silent": "s-eligibility"})
        # And it changed nothing: the item is still unverifiable and unscored.
        self.assertEqual(result.n, 1)
        self.assertEqual(
            result.details["unverifiable"]["reasons"]["no_declaration"],
            ["silent"])

    def test_no_suggestion_when_the_passages_are_too_close_to_call(self):
        near = [{"id": "s-a", "text": "Applications close on March 31 at 5 pm."},
                {"id": "s-b", "text": "Applications close on March 31 at 5 pm "
                                      "in every office."}]
        items = [answer_item("silent", "Applications close on March 31 at 5 pm.",
                             sources=["s-a", "s-b"]),
                 answer_item("declared", "Applications close in every office.",
                             sources=["s-a", "s-b"], answering_sources=["s-b"])]
        evidence = load(write_bundle(
            self.root, items,
            [response("silent", "Applications close on March 31. [s-a]"),
             response("declared", "Applications close in every office. [s-b]")],
            name="ambiguous", sources=near))
        result = self.run_suite("passage_attribution", evidence, 0.5)
        self.assertEqual(result.details["suggested_declarations"], {})

    def test_no_suggestion_for_an_item_with_one_candidate_passage(self):
        items = [_item("declared"),
                 answer_item("single", ELIGIBILITY, sources=["s-eligibility"])]
        evidence = self.bundle(items, [response("declared", RIGHT_PARAGRAPH),
                                       response("single", RIGHT_PARAGRAPH)],
                               name="single-source")
        result = self.run_suite("passage_attribution", evidence, 0.95)
        self.assertEqual(result.details["suggested_declarations"], {})


if __name__ == "__main__":
    unittest.main()
