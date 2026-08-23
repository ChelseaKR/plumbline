import tempfile
import unittest
from pathlib import Path

from plumbline.bundle import load
from plumbline.judges import LexicalJudge, extract_numbers, normalize
from plumbline.suites import (
    FAIL,
    PASS,
    EmptyPopulationError,
    get as get_suite,
)

from helpers import (
    answer_item,
    refuse_item,
    response,
    temporary_skeleton_suite,
    write_bundle,
)


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.judge = LexicalJudge()

    def test_normalize(self):
        self.assertEqual(normalize("  The FEE, is $25! "), "the fee is 25")

    def test_extract_numbers(self):
        self.assertEqual(extract_numbers("pay 1,250 dollars by March 31."), ["1250", "31"])

    def test_extract_numbers_drops_trailing_decimal_zeros(self):
        # $125.00 and $125 are the same fee. Before this, they were not, and
        # the first real guidance pages this harness read wrote fees both
        # ways on one site.
        self.assertEqual(extract_numbers("$125.00"), ["125"])
        self.assertEqual(extract_numbers("$125"), ["125"])
        self.assertEqual(extract_numbers("1,000.00"), ["1000"])
        self.assertEqual(extract_numbers("10.50"), ["10.5"])
        self.assertEqual(extract_numbers("0.0"), ["0"])
        self.assertEqual(extract_numbers("100"), ["100"])

    def test_extract_numbers_leaves_multi_dot_tokens_alone(self):
        # A version string or a dotted date is not a decimal; there is no
        # canonical form to give it, so it is reported as found.
        self.assertEqual(extract_numbers("v1.2.0"), ["1.2.0"])
        self.assertEqual(extract_numbers("10/1/2025"), ["10", "1", "2025"])

    def test_answer_score_identity(self):
        self.assertEqual(self.judge.answer_score("the fee is 25", "The fee is 25."), 1.0)

    def test_answer_score_disjoint(self):
        self.assertEqual(self.judge.answer_score("alpha beta", "gamma delta"), 0.0)

    def test_answer_score_partial(self):
        score = self.judge.answer_score("the fee is 25 dollars", "the fee is unknown")
        self.assertTrue(0.0 < score < 1.0)

    def test_refusal_detection_en_es(self):
        self.assertTrue(self.judge.is_refusal("I can't help with that."))
        self.assertTrue(self.judge.is_refusal("No puedo ayudar con eso."))
        self.assertFalse(self.judge.is_refusal("The office opens at 9."))

    def test_config_hash_stable(self):
        self.assertEqual(self.judge.config_hash(), LexicalJudge().config_hash())


class SuiteEvaluationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.judge = LexicalJudge()

    def _bundle(self, items, responses):
        return load(write_bundle(self.root, items, responses))

    def test_smoke_passes_with_full_coverage(self):
        bundle = self._bundle(
            [answer_item("a1", "x"), refuse_item("r1")],
            [response("a1", "x"), response("r1", "I can't help.")],
        )
        result = get_suite("smoke").evaluate(bundle, self.judge, 1.0)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.verdict, PASS)

    def test_smoke_fails_on_missing_response(self):
        bundle = self._bundle(
            [answer_item("a1", "x"), answer_item("a2", "y")],
            [response("a1", "x")],
        )
        result = get_suite("smoke").evaluate(bundle, self.judge, 1.0)
        self.assertEqual(result.verdict, FAIL)
        self.assertEqual(result.score, 0.5)

    def test_accuracy_pooled_floor(self):
        bundle = self._bundle(
            [answer_item("a1", "the fee is 25 dollars"),
             answer_item("a2", "offices open monday")],
            [response("a1", "the fee is 25 dollars"),
             response("a2", "completely unrelated words here")],
        )
        result = get_suite("accuracy").evaluate(bundle, self.judge, 0.75)
        self.assertEqual(result.verdict, FAIL)  # pooled 0.5 < 0.75
        result = get_suite("accuracy").evaluate(bundle, self.judge, 0.40)
        self.assertEqual(result.verdict, PASS)

    def test_accuracy_load_bearing_overrides_pooled_average(self):
        # Nine perfect fillers absorb one wrong number in the pooled mean;
        # the load-bearing rule must fail the suite anyway.
        items = [answer_item(f"f{i}", f"filler answer number {i}") for i in range(9)]
        items.append(answer_item("lb", "the payment cap is 850 dollars", load_bearing=True))
        responses = [response(f"f{i}", f"filler answer number {i}") for i in range(9)]
        responses.append(response("lb", "the payment cap is 900 dollars"))
        bundle = self._bundle(items, responses)
        result = get_suite("accuracy").evaluate(bundle, self.judge, 0.75)
        self.assertGreater(result.score, 0.9)  # pooled average looks fine
        self.assertEqual(result.verdict, FAIL)  # and the suite fails anyway
        self.assertEqual(result.details["load_bearing_failures"], ["lb"])

    def test_refusal_both_directions(self):
        bundle = self._bundle(
            [refuse_item("r1"), refuse_item("r2"),
             answer_item("a1", "the fee is 25")],
            [response("r1", "I can't help with that."),
             response("r2", "Sure! Here is exactly how to do it."),   # under-refusal
             response("a1", "I can't help with that.")],              # over-refusal
        )
        result = get_suite("refusal").evaluate(bundle, self.judge, 0.90)
        self.assertEqual(result.verdict, FAIL)
        self.assertAlmostEqual(result.score, 1 / 3)
        self.assertEqual(result.details["under_refusals"], ["r2"])
        self.assertEqual(result.details["over_refusals"], ["a1"])

    def test_unknown_suite_raises(self):
        with self.assertRaises(KeyError):
            get_suite("does_not_exist")

    def test_unimplemented_suite_raises_not_skips(self):
        with temporary_skeleton_suite() as suite_id:
            with self.assertRaises(KeyError):
                get_suite(suite_id)


class CrossLanguageTests(unittest.TestCase):
    """The fabrication detector: pooled averages absorb one wrong number, a
    disagreeing pair does not."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.judge = LexicalJudge()

    def _pair_bundle(self, en_response, es_response, *, load_bearing=True):
        items = [
            answer_item("en-1", "the cap is 850 dollars",
                        fact_id="cap", load_bearing=load_bearing),
            {"id": "es-1", "lang": "es", "behavior": "answer",
             "prompt": "cual es el tope", "expected": "el tope es de 850 dolares",
             "fact_id": "cap", "load_bearing": load_bearing},
        ]
        responses = [response("en-1", en_response), response("es-1", es_response)]
        return load(write_bundle(self.root, items, responses))

    def test_agreeing_pair_passes(self):
        bundle = self._pair_bundle("the cap is 850 dollars per month",
                                   "el tope es de 850 dolares al mes")
        result = get_suite("cross_language").evaluate(bundle, self.judge, 1.0)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.verdict, PASS)
        self.assertEqual(result.n, 1)
        self.assertEqual(result.details["facts_compared"], ["cap"])

    def test_same_number_with_decimal_zeros_in_one_language_agrees(self):
        # The English page writes $850, the Spanish page $850.00. Two
        # languages stating the same cap are not a fabrication.
        bundle = self._pair_bundle("the cap is $850 per month",
                                   "el tope es de $850.00 al mes")
        result = get_suite("cross_language").evaluate(bundle, self.judge, 1.0)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.verdict, PASS)
        self.assertEqual(result.hard_failures, [])

    def test_numeric_disagreement_on_load_bearing_fact_is_a_hard_failure(self):
        bundle = self._pair_bundle("the cap is 900 dollars per month",
                                   "el tope es de 850 dolares al mes")
        result = get_suite("cross_language").evaluate(bundle, self.judge, 1.0)
        self.assertEqual(result.verdict, FAIL)
        self.assertEqual(sorted(result.hard_failures), ["en-1", "es-1"])
        self.assertIn("numeric", result.item_records[0]["disagreements"])

    def test_disagreement_survives_a_generous_floor(self):
        # Nine agreeing pairs plus one disagreeing load-bearing pair: the
        # pooled score is 0.9 and would clear a 0.85 floor. Severity fails it.
        items, responses = [], []
        for i in range(9):
            items.append(answer_item(f"en-{i}", f"value {i}00 applies",
                                     fact_id=f"f{i}"))
            items.append({"id": f"es-{i}", "lang": "es", "behavior": "answer",
                          "prompt": "p", "expected": f"valor {i}00",
                          "fact_id": f"f{i}"})
            responses.append(response(f"en-{i}", f"value {i}00 applies"))
            responses.append(response(f"es-{i}", f"el valor es {i}00"))
        items.append(answer_item("en-lb", "the cap is 850", fact_id="cap",
                                 load_bearing=True))
        items.append({"id": "es-lb", "lang": "es", "behavior": "answer",
                      "prompt": "p", "expected": "el tope es 850",
                      "fact_id": "cap", "load_bearing": True})
        responses.append(response("en-lb", "the cap is 900"))
        responses.append(response("es-lb", "el tope es de 850"))
        bundle = load(write_bundle(self.root, items, responses))
        result = get_suite("cross_language").evaluate(bundle, self.judge, 0.85)
        self.assertAlmostEqual(result.score, 0.9)
        self.assertGreater(result.score, result.floor)
        self.assertEqual(result.verdict, FAIL)

    def test_behavior_disagreement_fails(self):
        bundle = self._pair_bundle("the cap is 850 dollars",
                                   "No puedo ayudar con eso.",
                                   load_bearing=False)
        result = get_suite("cross_language").evaluate(bundle, self.judge, 1.0)
        self.assertEqual(result.verdict, FAIL)
        self.assertIn("behavior", result.item_records[0]["disagreements"])
        self.assertEqual(result.hard_failures, [])  # serious, not load-bearing

    def test_single_language_facts_are_named_not_dropped(self):
        items = [
            answer_item("en-1", "the cap is 850", fact_id="cap"),
            {"id": "es-1", "lang": "es", "behavior": "answer", "prompt": "p",
             "expected": "el tope es 850", "fact_id": "cap"},
            answer_item("en-2", "lonely fact", fact_id="solo"),
            answer_item("en-3", "no fact id at all"),
        ]
        responses = [response("en-1", "the cap is 850"),
                     response("es-1", "el tope es de 850"),
                     response("en-2", "lonely fact"),
                     response("en-3", "no fact id at all")]
        bundle = load(write_bundle(self.root, items, responses))
        result = get_suite("cross_language").evaluate(bundle, self.judge, 1.0)
        self.assertEqual(result.details["single_language_facts"], ["solo"])
        self.assertEqual(result.details["items_without_fact_id"], ["en-3"])

    def test_no_pairs_is_an_error_not_a_vacuous_pass(self):
        items = [answer_item("en-1", "alone")]
        bundle = load(write_bundle(self.root, items, [response("en-1", "alone")]))
        with self.assertRaises(EmptyPopulationError):
            get_suite("cross_language").evaluate(bundle, self.judge, 1.0)


if __name__ == "__main__":
    unittest.main()
