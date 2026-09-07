"""Structural accessibility checks on a captured interface snapshot."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plumbline.bundle import load
from plumbline.judges import LexicalJudge
from plumbline.stats import KIND_CENSUS
from plumbline.suites import FAIL, PASS, EmptyPopulationError, get as get_suite
from plumbline.suites.accessibility import (
    contrast_ratio,
    normalise_text,
    relative_luminance,
)

from helpers import answer_item, response, write_bundle

GOOD_CONTRAST = """[
  {"name": "body text", "foreground": "#1a1c1e", "background": "#ffffff"},
  {"name": "primary button", "foreground": "#ffffff", "background": "#0b5d3b"}
]"""

BAD_CONTRAST = """[
  {"name": "hint text", "foreground": "#b9c2cc", "background": "#ffffff"}
]"""


def interface(*, lang='lang="en"', contrast=GOOD_CONTRAST, live=True,
              labelled=True, headings="<h1>Navigator</h1><h2>Ask</h2>",
              extra="", trailing="", computed=None):
    live_attrs = ' role="log" aria-live="polite"' if live else ""
    label = '<label for="q">Your question</label>' if labelled else ""
    contrast_block = (
        f'<script type="application/json" id="plumbline-contrast">{contrast}'
        f'</script>' if contrast is not None else ""
    )
    computed_block = (
        f'<script type="application/json" id="plumbline-computed-contrast">'
        f'{computed}</script>' if computed is not None else ""
    )
    return f"""<html {lang}>
<head><meta charset="utf-8"><title>Navigator</title>{contrast_block}\
{computed_block}</head>
<body>
{headings}
<div id="transcript"{live_attrs}></div>
<form>
{label}
<textarea id="q" name="q"></textarea>
<input type="submit" value="Send">
{extra}
</form>
{trailing}
</body>
</html>
"""


#: The text runs `interface()` renders, in document order, as the suite
#: normalises them. A computed block has to account for every one of them.
DEFAULT_RUNS = ("Navigator", "Ask", "Your question")


def computed_block(runs=DEFAULT_RUNS, *, foreground="#1a1c1e",
                   background="#ffffff", source="computed", skipped=(),
                   extra_pairs=()):
    """A capture block covering `runs`, all at a passing colour by default."""
    pairs = [
        {"name": f"run-{i}", "text": text, "foreground": foreground,
         "background": background, "size": "normal"}
        for i, text in enumerate(runs)
    ]
    pairs.extend(extra_pairs)
    return json.dumps({
        "source": source,
        "tool": "playwright/chromium 131.0.0",
        "url": "https://example.invalid/assistant",
        "pairs": pairs,
        "skipped": list(skipped),
    })


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

    def test_an_unlabelled_button_fails_and_names_it(self):
        result = self._evaluate(interface(extra='<button id="send"></button>'))
        self.assertIn("control_labels", result.details["failed_checks"])
        self.assertIn("send", self._detail(result, "control_labels")["detail"])

    def test_a_button_named_by_its_own_text_passes(self):
        result = self._evaluate(
            interface(extra='<button id="send">Send question</button>'))
        self.assertEqual(result.details["failed_checks"], [])

    def test_an_unclosed_button_does_not_take_the_page_as_its_name(self):
        # A `<button>` with no end tag collects every word after it. Reading
        # that as the button's accessible name reports an unlabelled control
        # as labelled, which is the false pass this check exists to prevent.
        result = self._evaluate(interface(
            extra='<button id="send">',
            trailing="<p>Riverbend County accepts walk-ins Monday to Friday.</p>",
        ))
        detail = self._detail(result, "control_labels")["detail"]
        self.assertIn("control_labels", result.details["failed_checks"])
        self.assertIn("send", detail)
        self.assertIn("</button>", detail)

    def test_aria_hidden_text_does_not_name_a_button(self):
        # Hidden from the accessibility tree is hidden from the accessible
        # name computation: a screen reader announces nothing here.
        result = self._evaluate(interface(
            extra='<button id="send"><span aria-hidden="true">Send</span></button>'))
        detail = self._detail(result, "control_labels")["detail"]
        self.assertIn("control_labels", result.details["failed_checks"])
        self.assertIn("send", detail)
        self.assertIn("aria-hidden", detail)

    def test_a_button_with_a_hidden_icon_and_visible_text_still_passes(self):
        result = self._evaluate(interface(
            extra=('<button id="send"><span aria-hidden="true">&#x2192;</span>'
                   'Send</button>')))
        self.assertEqual(result.details["failed_checks"], [])

    def test_an_image_alt_inside_a_button_names_it(self):
        result = self._evaluate(interface(
            extra='<button id="send"><img src="s.svg" alt="Send question"></button>'))
        self.assertEqual(result.details["failed_checks"], [])

    def test_a_decorative_image_alone_does_not_name_a_button(self):
        result = self._evaluate(interface(
            extra='<button id="send"><img src="s.svg" alt=""></button>'))
        self.assertIn("control_labels", result.details["failed_checks"])

    def test_a_text_attribute_is_not_an_accessible_name(self):
        # `text` is not an HTML attribute an assistive technology reads. It is
        # here because collecting a button's text into its own attribute map
        # under that key would make this markup pass.
        result = self._evaluate(
            interface(extra='<button id="send" text="Send"></button>'))
        self.assertIn("control_labels", result.details["failed_checks"])

    def test_a_whitespace_only_accessible_name_is_not_a_name(self):
        result = self._evaluate(
            interface(extra='<button id="send" aria-label=" "></button>'))
        self.assertIn("control_labels", result.details["failed_checks"])

    def test_a_button_labelled_the_ordinary_ways_passes(self):
        for markup in (
            '<button id="send" aria-label="Send question"></button>',
            '<button id="send" title="Send question"></button>',
            '<label for="send">Send</label><button id="send"></button>',
        ):
            with self.subTest(markup=markup):
                result = self._evaluate(interface(extra=markup))
                self.assertEqual(result.details["failed_checks"], [])

    def test_script_text_inside_a_button_does_not_name_it(self):
        result = self._evaluate(interface(
            extra='<button id="send"><script>var label = "Send";</script></button>'))
        self.assertIn("control_labels", result.details["failed_checks"])

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

    # --- computed pairs -----------------------------------------------------
    #
    # The declared block is a list the page writes about itself, so it can be
    # complete about its passing pairs and silent about the rest. These tests
    # are about the source that cannot be silent: a capture is checked against
    # the markup it sits in.

    def test_the_declared_path_says_so_and_carries_its_caveat(self):
        result = self._evaluate(interface())
        record = self._detail(result, "contrast_declarations")
        self.assertEqual(record["contrast_source"], "declared")
        self.assertIn("a pair that fails can be left out", record["caveat"])
        self.assertIn("self-declared pairs", record["detail"])
        self.assertEqual(result.details["contrast_source"], "declared")

    def test_a_complete_capture_passes_and_names_its_source(self):
        result = self._evaluate(interface(computed=computed_block()))
        record = self._detail(result, "contrast_declarations")
        self.assertEqual(record["score"], 1.0)
        self.assertEqual(record["contrast_source"], "computed")
        self.assertNotIn("caveat", record)
        self.assertEqual(result.details["contrast_source"], "computed")
        self.assertIn("every text run in the snapshot accounted for",
                      record["detail"])

    def test_the_capture_finds_the_failing_pair_the_declaration_left_out(self):
        """#70's fixture: the same page passes declared and fails captured.

        The declared block lists only the colours that pass. The capture has to
        account for every text run in the markup, so the hint text it left out
        arrives with its real colour and its real ratio.
        """
        page = interface(
            trailing='<p id="hint">Answers may take a moment.</p>',
            computed=computed_block(
                runs=("Navigator", "Ask", "Your question"),
                extra_pairs=[{
                    "name": "p#hint", "text": "Answers may take a moment.",
                    "foreground": "#b9c2cc", "background": "#ffffff",
                    "size": "normal",
                }],
            ),
        )
        declared_only = interface(
            trailing='<p id="hint">Answers may take a moment.</p>')

        passed_declared = self._evaluate(declared_only)
        self.assertNotIn("contrast_declarations",
                         passed_declared.details["failed_checks"])
        self.assertIn("self-declared pairs",
                      self._detail(passed_declared,
                                   "contrast_declarations")["detail"])

        failed_computed = self._evaluate(page)
        detail = self._detail(failed_computed, "contrast_declarations")["detail"]
        self.assertIn("contrast_declarations",
                      failed_computed.details["failed_checks"])
        self.assertIn("p#hint", detail)
        self.assertIn("needs 4.5:1", detail)

    def test_a_capture_missing_a_text_run_fails_and_names_it(self):
        """Omission is the whole threat, and omission is what this sees.

        Removing the pair for text the markup still contains leaves that text
        unaccounted for, which is exactly the shape a pair deleted for failing
        would take.
        """
        result = self._evaluate(interface(
            computed=computed_block(runs=("Navigator", "Ask"))))
        detail = self._detail(result, "contrast_declarations")["detail"]
        self.assertIn("contrast_declarations", result.details["failed_checks"])
        self.assertIn("does not account for", detail)
        self.assertIn("Your question", detail)

    def test_a_repeated_text_run_needs_a_pair_each_time(self):
        """A multiset, not a set: the same sentence twice in two colours.

        With a set comparison the second, failing occurrence could be dropped
        and the first would cover for it.
        """
        result = self._evaluate(interface(
            trailing="<p>Ask</p>", computed=computed_block()))
        detail = self._detail(result, "contrast_declarations")["detail"]
        self.assertIn("does not account for", detail)

    def test_an_empty_capture_is_a_failure_not_a_clean_page(self):
        """A capture that recorded nothing is not a capture that found nothing.

        This is the failed-capture case: the tool crashed or matched no nodes,
        and an empty `pairs` list reading as "computed, all pass" would turn a
        broken tool into the best possible score.
        """
        result = self._evaluate(interface(computed=computed_block(runs=())))
        detail = self._detail(result, "contrast_declarations")["detail"]
        self.assertIn("contrast_declarations", result.details["failed_checks"])
        self.assertIn("recorded nothing", detail)

    def test_the_computed_marker_is_not_taken_at_its_word(self):
        result = self._evaluate(interface(
            computed=computed_block(source="hand-written")))
        detail = self._detail(result, "contrast_declarations")["detail"]
        self.assertIn("contrast_declarations", result.details["failed_checks"])
        self.assertIn("hand-written", detail)

    def test_a_pair_with_no_text_cannot_be_matched_and_fails(self):
        block = json.dumps({
            "source": "computed", "pairs": [
                {"name": "body", "foreground": "#000", "background": "#fff"}],
        })
        result = self._evaluate(interface(computed=block))
        self.assertIn("carries no `text`",
                      self._detail(result, "contrast_declarations")["detail"])

    def test_a_skipped_node_needs_a_stated_reason(self):
        """A node dropped without a reason is a node left out.

        The renderer legitimately paints nothing for `display:none`, so a
        capture may skip it -- but not silently, or `skipped` becomes the
        place a failing pair goes to disappear.
        """
        result = self._evaluate(interface(computed=computed_block(
            runs=("Navigator", "Ask"),
            skipped=[{"text": "Your question", "reason": ""}])))
        self.assertIn("non-empty `reason`",
                      self._detail(result, "contrast_declarations")["detail"])

    def test_a_skipped_node_with_a_reason_is_accounted_for(self):
        result = self._evaluate(interface(computed=computed_block(
            runs=("Navigator", "Ask"),
            skipped=[{"text": "Your question", "reason": "display:none"}])))
        record = self._detail(result, "contrast_declarations")
        self.assertEqual(record["score"], 1.0)
        self.assertIn("1 not painted by the renderer", record["detail"])

    def test_an_unusable_capture_does_not_fall_back_to_the_declaration(self):
        """A broken capture must not score the same as a good one.

        Falling back would mean the way to make a failing capture pass is to
        break it, and the report would say `declared` while a `computed` block
        sat in the file.
        """
        result = self._evaluate(interface(contrast=GOOD_CONTRAST,
                                          computed="{not json"))
        record = self._detail(result, "contrast_declarations")
        self.assertEqual(record["score"], 0.0)
        self.assertEqual(record["contrast_source"], "computed")
        self.assertIn("not valid JSON", record["detail"])

    def test_a_capture_needs_no_declaration_block(self):
        result = self._evaluate(interface(contrast=None,
                                          computed=computed_block()))
        self.assertEqual(
            self._detail(result, "contrast_declarations")["score"], 1.0)


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


class TheCaptureToolIsOutsideTheGate(unittest.TestCase):
    """`plumbline gate` must not depend on a browser to run.

    The capture is an input, like a recording. If any module under
    `plumbline.` reached `playwright`, running the gate on a machine with no
    browser would stop working, and the offline stdlib-only promise the whole
    project rests on would have quietly acquired a 300MB dependency.
    """

    def test_no_plumbline_module_imports_playwright(self):
        script = (
            "import sys, pkgutil, importlib\n"
            "import plumbline\n"
            # `plumbline.__main__` parses argv at import time, so importing it
            # here would run the CLI rather than load a module.
            "for m in pkgutil.walk_packages(plumbline.__path__, 'plumbline.'):\n"
            "    if m.name.endswith('.__main__'):\n"
            "        continue\n"
            "    importlib.import_module(m.name)\n"
            "hits = [n for n in sys.modules if n.split('.')[0] == 'playwright']\n"
            "print('|'.join(hits))\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True,
            env={"PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
                 "PATH": "/usr/bin:/bin"},
            check=True,
        )
        self.assertEqual(out.stdout.strip(), "", "a plumbline module imported playwright")

    def test_the_capture_tool_does_not_import_playwright_at_module_scope(self):
        source = (Path(__file__).resolve().parent.parent
                  / "tools" / "capture_interface.py").read_text(encoding="utf-8")
        for line in source.splitlines():
            if line.startswith(("import ", "from ")):
                self.assertNotIn("playwright", line,
                                 "playwright is imported at module scope, so "
                                 "`--help` would need a browser installed")

    def test_the_capture_normalises_text_the_way_the_suite_does(self):
        """Both sides of the completeness check must agree on whitespace.

        They are written in different languages, so nothing but a test holds
        them together; if they drift, every honest capture reads as incomplete
        and the check gets switched off for being wrong.
        """
        source = (Path(__file__).resolve().parent.parent
                  / "tools" / "capture_interface.py").read_text(encoding="utf-8")
        self.assertIn('s.split(/\\s+/).filter(Boolean).join(" ")', source)
        for raw in ("  Ask   a\n question ", "Ask a question", "\tAsk a question\n"):
            self.assertEqual(normalise_text(raw), " ".join(raw.split()))

    def test_the_block_a_recapture_writes_replaces_the_previous_one(self):
        from importlib.util import module_from_spec, spec_from_file_location
        path = (Path(__file__).resolve().parent.parent
                / "tools" / "capture_interface.py")
        spec = spec_from_file_location("capture_interface", path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        first = module.insert_block(
            "<html><head><title>x</title></head><body>a</body></html>",
            module.render_block({"pairs": [], "skipped": []}, "u", "t"))
        second = module.insert_block(
            first, module.render_block({"pairs": [], "skipped": []}, "u2", "t"))
        self.assertEqual(second.count("plumbline-computed-contrast"), 1)
        self.assertIn('"url": "u2"', second)


if __name__ == "__main__":
    unittest.main()
