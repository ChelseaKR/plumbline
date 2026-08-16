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

    def test_it_says_the_dataset_is_not_a_benchmark(self):
        self.assertIn("not a benchmark", self.page)


if __name__ == "__main__":
    unittest.main()
