"""Structural accessibility checks on a captured interface snapshot."""

import tempfile
import unittest
from pathlib import Path

from plumbline.bundle import load
from plumbline.judges import LexicalJudge
from plumbline.stats import KIND_CENSUS
from plumbline.suites import FAIL, PASS, EmptyPopulationError, get as get_suite
from plumbline.suites.accessibility import contrast_ratio, relative_luminance

from helpers import answer_item, response, write_bundle

GOOD_CONTRAST = """[
  {"name": "body text", "foreground": "#1a1c1e", "background": "#ffffff"},
  {"name": "primary button", "foreground": "#ffffff", "background": "#0b5d3b"}
]"""

BAD_CONTRAST = """[
  {"name": "hint text", "foreground": "#b9c2cc", "background": "#ffffff"}
]"""


def interface(*, lang='lang="en"', contrast=GOOD_CONTRAST, live=True,
              labelled=True, headings="<h1>Navigator</h1><h2>Ask</h2>"):
    live_attrs = ' role="log" aria-live="polite"' if live else ""
    label = '<label for="q">Your question</label>' if labelled else ""
    contrast_block = (
        f'<script type="application/json" id="plumbline-contrast">{contrast}'
        f'</script>' if contrast is not None else ""
    )
    return f"""<html {lang}>
<head><meta charset="utf-8"><title>Navigator</title>{contrast_block}</head>
<body>
{headings}
<div id="transcript"{live_attrs}></div>
<form>
{label}
<textarea id="q" name="q"></textarea>
<input type="submit" value="Send">
</form>
</body>
</html>
"""


class ColorMathTests(unittest.TestCase):
    def test_luminance_endpoints(self):
        self.assertAlmostEqual(relative_luminance("#000000"), 0.0)
        self.assertAlmostEqual(relative_luminance("#ffffff"), 1.0)

    def test_black_on_white_is_21_to_1(self):
        self.assertAlmostEqual(contrast_ratio("#000000", "#ffffff"), 21.0, places=2)

    def test_shorthand_hex(self):
        self.assertAlmostEqual(contrast_ratio("#000", "#fff"), 21.0, places=2)

    def test_order_does_not_matter(self):
        self.assertAlmostEqual(contrast_ratio("#0b5d3b", "#ffffff"),
                               contrast_ratio("#ffffff", "#0b5d3b"))

    def test_bad_colour_rejected(self):
        with self.assertRaises(ValueError):
            relative_luminance("teal")


class AccessibilitySuiteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.judge = LexicalJudge()
        self._counter = 0

    def _evaluate(self, html, floor=1.0):
        self._counter += 1
        bundle = load(write_bundle(
            self.root, [answer_item("a1", "x")], [response("a1", "x")],
            name=f"iface-{self._counter}", interface=html,
        ))
        return get_suite("accessibility").evaluate(bundle, self.judge, floor)

    def _detail(self, result, check):
        return next(r for r in result.item_records if r["check"] == check)

    def test_conforming_snapshot_passes_every_check(self):
        result = self._evaluate(interface())
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.verdict, PASS)
        self.assertEqual(result.n, 5)
        self.assertEqual(result.details["failed_checks"], [])

    def test_missing_language_declaration_fails(self):
        result = self._evaluate(interface(lang=""))
        self.assertEqual(result.verdict, FAIL)
        self.assertIn("language_declaration", result.details["failed_checks"])

    def test_unlabelled_control_fails_and_names_it(self):
        result = self._evaluate(interface(labelled=False))
        self.assertIn("control_labels", result.details["failed_checks"])
        self.assertIn("q", self._detail(result, "control_labels")["detail"])

    def test_missing_live_region_fails(self):
        result = self._evaluate(interface(live=False))
        self.assertIn("live_region", result.details["failed_checks"])

    def test_skipped_heading_level_fails(self):
        result = self._evaluate(
            interface(headings="<h1>Navigator</h1><h3>Ask</h3>"))
        detail = self._detail(result, "heading_order")["detail"]
        self.assertIn("h1 to h3", detail)

    def test_two_h1s_fail(self):
        result = self._evaluate(
            interface(headings="<h1>One</h1><h1>Two</h1>"))
        self.assertIn("exactly one h1", self._detail(result, "heading_order")["detail"])

    def test_low_contrast_pair_fails_with_the_computed_ratio(self):
        result = self._evaluate(interface(contrast=BAD_CONTRAST))
        detail = self._detail(result, "contrast_declarations")["detail"]
        self.assertIn("hint text", detail)
        self.assertIn("needs 4.5:1", detail)

    def test_large_text_uses_the_lower_threshold(self):
        borderline = ('[{"name": "heading", "foreground": "#767676", '
                      '"background": "#ffffff", "size": "large"}]')
        result = self._evaluate(interface(contrast=borderline))
        self.assertTrue(self._detail(result, "contrast_declarations")["score"])

    def test_undeclared_contrast_fails_rather_than_being_assumed(self):
        result = self._evaluate(interface(contrast=None))
        detail = self._detail(result, "contrast_declarations")["detail"]
        self.assertIn("unverified contrast is not passing contrast", detail)

    def test_malformed_contrast_declaration_fails(self):
        result = self._evaluate(interface(contrast="{not json"))
        self.assertIn("contrast_declarations", result.details["failed_checks"])

    def test_statistics_are_refused_because_this_is_a_census(self):
        result = self._evaluate(interface())
        self.assertEqual(result.score_kind, KIND_CENSUS)

    def test_no_interface_in_the_bundle_is_an_error(self):
        bundle = load(write_bundle(
            self.root, [answer_item("a1", "x")], [response("a1", "x")],
            name="no-iface",
        ))
        with self.assertRaises(EmptyPopulationError):
            get_suite("accessibility").evaluate(bundle, self.judge, 1.0)


if __name__ == "__main__":
    unittest.main()
