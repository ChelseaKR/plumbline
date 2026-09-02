"""The published page must be what the committed evidence produces.

`site/index.html` is deployed to GitHub Pages, so it is a provenance claim
made to people who will never clone this repository. A page that had drifted
from the committed report — by a hand edit, or by an artifact regenerating
underneath it — would be exactly the unbackable claim this harness exists to
refuse, in the one repository where that is unforgivable.

So the page is generated from the committed artifacts by
`tools/build_site.py`, which runs the refusals it renders rather than
describing them, and this file checks two things: that the committed page is
current, and that the check can actually fail. A verification that cannot fail
is the vacuous pass wearing a different hat.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import build_site  # noqa: E402


class ThePublishedPageIsCurrent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # One build for the whole class: it runs three gates and two verifies.
        cls.data = build_site.collect()
        cls.page = build_site.render(cls.data)

    def test_the_committed_page_is_what_todays_evidence_produces(self):
        self.assertEqual(
            build_site.PAGE.read_text(encoding="utf-8"), self.page,
            "site/index.html is stale; run `python3 tools/build_site.py`")

    def test_the_check_command_agrees(self):
        self.assertEqual(build_site.main(["--check"]), 0)

    def test_a_drifted_page_is_caught(self):
        # The failure this file exists for: the committed page says one thing
        # and the committed report says another.
        drifted = json.loads(json.dumps(self.data))
        drifted["report"]["suites"][0]["score"] = 0.4242
        self.assertNotEqual(build_site.render(drifted), self.page)
        self.assertNotIn("0.4242", self.page)

    def test_a_moved_run_id_stops_the_build_rather_than_republishing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            scratch = build_site._scratch_repo(Path(tmp))
            with self.assertRaises(build_site.DrillFailed):
                build_site.clean_run(scratch, "0" * 16)

    def test_the_page_carries_the_committed_identities(self):
        provenance = self.data["report"]["provenance"]
        for value in (provenance["run_id"],
                      provenance["dataset_id"],
                      provenance["report_sha256"][:12],
                      provenance["judge_config_sha256"][:12]):
            self.assertIn(value, self.page)

    def test_the_page_shows_the_refusals_it_claims(self):
        self.assertIn("INTEGRITY REFUSAL", self.page)
        # Both refusal paths, not just the one that existed first.
        self.assertIn("does not match its own seal", self.page)
        self.assertIn("its own contents generate", self.page)
        self.assertIn("content mismatch: responses.jsonl", self.page)

    def test_it_is_self_contained(self):
        # A strict reader with no network gets the same page: no external
        # stylesheet, script, font or image.
        for external in ("http://", "src=", "<script", "@import", "//cdn"):
            with self.subTest(external=external):
                self.assertNotIn(external, self.page.replace(
                    'href="https://github.com', ""))

    def test_the_head_names_this_page_and_not_the_shared_origin(self):
        # This page is served under a project PATH on `chelseakr.github.io`, an
        # origin it shares with five other unrelated project sites. So a
        # canonical of "/" is not shorthand for this site's root; it is a
        # different address that 404s, and all six sites would claim it. A
        # crawler that believes them folds six projects into one document.
        #
        # The assertion is therefore not "a canonical exists" — an empty or
        # origin-rooted one passes that and is the bug — but that the canonical
        # is this page's full published URL, that og:url agrees with it, and
        # that the card repeats the page instead of describing it a second time.
        import re

        canonical = re.search(
            r'<link rel="canonical" href="([^"]*)">', self.page)
        self.assertIsNotNone(canonical, "the page has no canonical URL")
        self.assertEqual(canonical.group(1), build_site.PAGE_URL)

        def meta(attribute, name):
            found = re.search(
                rf'<meta {attribute}="{name}" content="([^"]*)">', self.page)
            self.assertIsNotNone(found, f"the page has no {name}")
            return found.group(1)

        self.assertEqual(meta("property", "og:url"), build_site.PAGE_URL)
        for url in (canonical.group(1), meta("property", "og:url")):
            self.assertNotEqual(
                url.rstrip("/"), "https://chelseakr.github.io",
                "that is the shared origin, which is a different site")
            self.assertIn("/plumbline/", url)

        title = re.search(r"<title>([^<]*)</title>", self.page)
        self.assertIsNotNone(title)
        self.assertEqual(meta("property", "og:title"), title.group(1))
        self.assertEqual(
            meta("name", "description"), meta("property", "og:description"))
        self.assertEqual(meta("property", "og:type"), "website")

        # A card tag that exists but carries an empty string is the absence
        # rendered as a value: it passes "the page has a title" and unfurls as
        # a blank box, which is the reading this repository refuses everywhere
        # else. So the assertion is on the content, not on the tag.
        for attribute, name in (("property", "og:title"),
                                ("property", "og:description"),
                                ("property", "og:image")):
            with self.subTest(card=name):
                self.assertTrue(
                    meta(attribute, name).strip(),
                    f"{name} is present but empty, which unfurls as nothing")

        # The card promises a large image, so a large image has to be there.
        # `summary_large_image` with nothing to show renders worse than
        # `summary`, and an og:image naming a file the deploy does not upload
        # is the same failure one step further away from where it is visible:
        # every gate stays green and the shared link renders blank. So the URL
        # is checked against the published tree, not just against itself.
        self.assertEqual(meta("name", "twitter:card"), "summary_large_image")
        image = meta("property", "og:image")
        self.assertEqual(image, build_site.PAGE_IMAGE_URL)
        self.assertEqual(meta("name", "twitter:image"), image)
        self.assertTrue(
            image.startswith("https://"),
            "a crawler resolving a share card has no base for a relative URL")
        self.assertIn("/plumbline/", image)
        published = build_site.SITE_DIR / build_site.PAGE_IMAGE
        self.assertTrue(
            published.is_file(),
            f"og:image names {build_site.PAGE_IMAGE}, which is not in site/")
        self.assertTrue(published.stat().st_size,
                        f"{published} is empty; that unfurls as nothing")
        self.assertTrue(meta("property", "og:image:alt").strip())

        # A description that wrapped across a source line put a literal newline
        # inside the content attribute of the published page. It reads fine and
        # is legal HTML, which is why it survived; it is still a stray control
        # character in the one string a search result quotes verbatim.
        for name in ("description", "og:description", "og:title"):
            attribute = "name" if name == "description" else "property"
            value = meta(attribute, name)
            self.assertNotIn("\n", value, f"{name} carries a newline")
            self.assertEqual(value, value.strip())

    def test_it_says_the_dataset_is_not_a_benchmark(self):
        self.assertIn("not a benchmark", self.page)


if __name__ == "__main__":
    unittest.main()
