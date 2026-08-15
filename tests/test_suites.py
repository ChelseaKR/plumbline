import tempfile
import unittest
from pathlib import Path

from plumbline.bundle import load
from plumbline.judges import LexicalJudge, extract_numbers, normalize
from plumbline.suites import FAIL, PASS, get as get_suite

from helpers import answer_item, refuse_item, response, write_bundle


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.judge = LexicalJudge()

    def test_normalize(self):
        self.assertEqual(normalize("  The FEE, is $25! "), "the fee is 25")

    def test_extract_numbers(self):
        self.assertEqual(extract_numbers("pay 1,250 dollars by March 31."), ["1250", "31"])

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

    def test_skeleton_suite_raises_not_skips(self):
        with self.assertRaises(KeyError):
            get_suite("cross_language")


if __name__ == "__main__":
    unittest.main()
