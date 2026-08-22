"""The published page is held to the same accessibility standard it holds a
target's interface to.

`tools/check_site_a11y.py` runs seven structural checks against
`site/index.html` itself — the same kind of check
`src/plumbline/suites/accessibility.py` runs against a target's captured
interface. This file checks that the committed page currently passes all
seven, and — because a check that cannot fail is the vacuous pass this whole
project argues against — that each individual check can actually catch the
defect it exists to catch.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_site_a11y as site_a11y  # noqa: E402


def _fake_snapshot(html: str) -> site_a11y._Snapshot:
    snapshot = site_a11y._Snapshot()
    snapshot.feed(html)
    snapshot.close()
    return snapshot


class TheCommittedPagePassesEveryCheck(unittest.TestCase):
    def test_the_command_exits_zero(self):
        self.assertEqual(site_a11y.main([]), 0)

    def test_every_declared_check_passed(self):
        results = site_a11y.run()
        failed = [name for name, passed, _ in results if not passed]
        self.assertEqual(failed, [])

    def test_it_actually_ran_all_seven_checks(self):
        # A check that silently stopped running would leave this file
        # asserting nothing about it, the same way a suite excluding a
        # response instead of scoring it can look identical to a pass.
        self.assertEqual(len(site_a11y.run()), 7)
        self.assertEqual(len({name for name, *_ in site_a11y.run()}), 7)


class EachCheckCanActuallyFail(unittest.TestCase):
    """One defect per check, planted in a minimal fixture. If any of these
    started passing, the check it exercises stopped checking anything."""

    def test_missing_language_declaration(self):
        snapshot = _fake_snapshot("<html><body><h1>x</h1></body></html>")
        self.assertFalse(site_a11y._check_language(snapshot)[0])

    def test_declared_language_passes(self):
        snapshot = _fake_snapshot(
            '<html lang="en"><body><h1>x</h1></body></html>')
        self.assertTrue(site_a11y._check_language(snapshot)[0])

    def test_no_headings_at_all(self):
        snapshot = _fake_snapshot("<html lang='en'><body><p>x</p></body></html>")
        self.assertFalse(site_a11y._check_heading_order(snapshot)[0])

    def test_two_h1s(self):
        snapshot = _fake_snapshot(
            "<body><h1>a</h1><h1>b</h1></body>")
        ok, detail = site_a11y._check_heading_order(snapshot)
        self.assertFalse(ok)
        self.assertIn("2", detail)

    def test_a_skipped_heading_level(self):
        snapshot = _fake_snapshot("<body><h1>a</h1><h3>b</h3></body>")
        ok, detail = site_a11y._check_heading_order(snapshot)
        self.assertFalse(ok)
        self.assertIn("h1", detail)
        self.assertIn("h3", detail)

    def test_well_ordered_headings_pass(self):
        snapshot = _fake_snapshot("<body><h1>a</h1><h2>b</h2><h3>c</h3></body>")
        self.assertTrue(site_a11y._check_heading_order(snapshot)[0])

    def test_a_link_with_no_text(self):
        snapshot = _fake_snapshot('<body><a href="/x"></a></body>')
        self.assertFalse(site_a11y._check_link_text(snapshot)[0])

    def test_a_generic_click_here_link(self):
        snapshot = _fake_snapshot('<body><a href="/x">click here</a></body>')
        ok, detail = site_a11y._check_link_text(snapshot)
        self.assertFalse(ok)
        self.assertIn("/x", detail)

    def test_a_page_with_no_links_passes_vacuously(self):
        snapshot = _fake_snapshot("<body><p>no links here</p></body>")
        self.assertTrue(site_a11y._check_link_text(snapshot)[0])

    def test_a_descriptive_link_passes(self):
        snapshot = _fake_snapshot(
            '<body><a href="/x">the committed report</a></body>')
        self.assertTrue(site_a11y._check_link_text(snapshot)[0])

    def test_an_image_with_no_alt(self):
        snapshot = _fake_snapshot('<body><img src="x.png"></body>')
        self.assertFalse(site_a11y._check_image_alt(snapshot)[0])

    def test_an_image_with_alt_passes(self):
        snapshot = _fake_snapshot('<body><img src="x.png" alt="a chart"></body>')
        self.assertTrue(site_a11y._check_image_alt(snapshot)[0])

    def test_a_page_with_no_images_passes_vacuously(self):
        snapshot = _fake_snapshot("<body><p>no images here</p></body>")
        self.assertTrue(site_a11y._check_image_alt(snapshot)[0])

    def test_no_main_landmark(self):
        snapshot = _fake_snapshot("<body><div>x</div></body>")
        self.assertFalse(site_a11y._check_main_landmark(snapshot)[0])

    def test_two_main_landmarks(self):
        snapshot = _fake_snapshot("<body><main>a</main><main>b</main></body>")
        ok, detail = site_a11y._check_main_landmark(snapshot)
        self.assertFalse(ok)
        self.assertIn("2", detail)

    def test_one_main_landmark_passes(self):
        snapshot = _fake_snapshot("<body><main>a</main></body>")
        self.assertTrue(site_a11y._check_main_landmark(snapshot)[0])

    def test_user_scalable_no_disables_zoom(self):
        snapshot = _fake_snapshot(
            '<html><head><meta name="viewport" '
            'content="width=device-width, user-scalable=no"></head></html>')
        self.assertFalse(site_a11y._check_zoom_not_disabled(snapshot)[0])

    def test_maximum_scale_below_two_disables_zoom(self):
        snapshot = _fake_snapshot(
            '<html><head><meta name="viewport" '
            'content="width=device-width, maximum-scale=1"></head></html>')
        self.assertFalse(site_a11y._check_zoom_not_disabled(snapshot)[0])

    def test_no_viewport_meta_at_all(self):
        snapshot = _fake_snapshot("<html><head></head></html>")
        self.assertFalse(site_a11y._check_zoom_not_disabled(snapshot)[0])

    def test_an_unrestricted_viewport_passes(self):
        snapshot = _fake_snapshot(
            '<html><head><meta name="viewport" '
            'content="width=device-width, initial-scale=1"></head></html>')
        self.assertTrue(site_a11y._check_zoom_not_disabled(snapshot)[0])

    def test_a_pair_that_fails_wcag_aa(self):
        page = """
        <html><head><style>
        :root { --bg: #ffffff; --fg: #f0f0f0; --muted: #f0f0f0; --rule: #ccc;
                --card: #ffffff; --accent: #f0f0f0; --ok: #f0f0f0;
                --stop: #f0f0f0; --code-bg: #ffffff; }
        @media (prefers-color-scheme: dark) {
          :root { --bg: #000; --fg: #fff; --muted: #fff; --rule: #333;
                   --card: #000; --accent: #fff; --ok: #fff; --stop: #fff;
                   --code-bg: #000; }
        }
        </style></head></html>
        """
        snapshot = _fake_snapshot(page)
        ok, detail = site_a11y._check_contrast(snapshot)
        self.assertFalse(ok)
        self.assertIn("light", detail)

    def test_no_style_block_at_all(self):
        snapshot = _fake_snapshot("<html><body>x</body></html>")
        self.assertFalse(site_a11y._check_contrast(snapshot)[0])

    def test_only_a_light_palette_declared(self):
        page = """
        <html><head><style>
        :root { --bg: #fff; --fg: #000; --muted: #333; --rule: #ccc;
                --card: #fff; --accent: #005; --ok: #050; --stop: #500;
                --code-bg: #eee; }
        </style></head></html>
        """
        snapshot = _fake_snapshot(page)
        self.assertFalse(site_a11y._check_contrast(snapshot)[0])


class TheMainEntryPoint(unittest.TestCase):
    def test_a_missing_page_is_refused_rather_than_crashing(self):
        original = site_a11y.PAGE
        try:
            site_a11y.PAGE = REPO / "site" / "does-not-exist.html"
            self.assertEqual(site_a11y.main([]), 1)
        finally:
            site_a11y.PAGE = original


if __name__ == "__main__":
    unittest.main()
