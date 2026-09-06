"""`plumbline diff`: what changed between two bundles.

The baseline comparison refuses to compare scores across a dataset hash change
and names the two hashes. These tests hold the verb that answers the next
question, and they hold it to the same rules the rest of the harness follows:
nothing is read from a bundle that did not verify, a difference that is found
is a difference that is printed, and a check that could not fail is not a
check.
"""

from __future__ import annotations

import io
import json
import contextlib
import dataclasses
import tempfile
import unittest
from pathlib import Path

from plumbline import cli
from plumbline.bundle import Item, IntegrityError
from plumbline.diff import diff_bundles, summarize_for_terminal

from helpers import answer_item, refuse_item, response, write_bundle


def _items():
    return [
        answer_item("rent-relief-en", "The maximum award is 850 dollars."),
        refuse_item("legal-advice-en"),
    ]


def _responses(amount="850"):
    return [
        response("rent-relief-en", f"The maximum award is {amount} dollars."),
        response("legal-advice-en", "I can't help with that."),
    ]


class DiffTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _bundle(self, name, items=None, responses=None, **kw):
        return write_bundle(self.root, items if items is not None else _items(),
                            responses if responses is not None else _responses(),
                            name=name, **kw)

    # --- the shape of the answer -------------------------------------------

    def test_a_bundle_against_itself_reports_no_difference(self):
        b = self._bundle("same")
        diff = diff_bundles(b, b)
        self.assertFalse(diff["changed"])
        self.assertFalse(diff["dataset_changed"])
        lines = summarize_for_terminal(diff)
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("no difference", lines[1])

    def test_a_planted_number_is_named_with_both_values(self):
        """The tamper drill's second run: a response's number was changed and
        the bundle legitimately re-sealed, so integrity passes and the baseline
        refuses to compare. This is the sentence the reader was missing."""
        before = self._bundle("before")
        after = self._bundle("after", responses=_responses("900"))
        diff = diff_bundles(before, after)

        self.assertTrue(diff["changed"])
        self.assertTrue(diff["dataset_changed"])
        changed = diff["responses"]["changed"]
        self.assertEqual([c["id"] for c in changed], ["rent-relief-en"])
        self.assertEqual(changed[0]["numbers_removed"], ["850"])
        self.assertEqual(changed[0]["numbers_added"], ["900"])

        line = [ln for ln in summarize_for_terminal(diff) if "rent-relief-en" in ln]
        self.assertEqual(len(line), 1, line)
        self.assertIn("850", line[0])
        self.assertIn("900", line[0])

    def test_added_and_removed_items_are_both_named(self):
        before = self._bundle("before")
        after = self._bundle(
            "after",
            items=[_items()[0], answer_item("new-en", "Something else.")],
            responses=[_responses()[0], response("new-en", "Something else.")],
        )
        diff = diff_bundles(before, after)
        self.assertEqual(diff["items"]["added"], ["new-en"])
        self.assertEqual(diff["items"]["removed"], ["legal-advice-en"])
        self.assertEqual(diff["responses"]["added"], ["new-en"])
        self.assertEqual(diff["responses"]["removed"], ["legal-advice-en"])

    def test_a_changed_item_is_reported_field_by_field(self):
        before = self._bundle("before")
        changed_item = dict(_items()[0])
        changed_item["expected"] = "The maximum award is 900 dollars."
        changed_item["load_bearing"] = True
        after = self._bundle("after", items=[changed_item, _items()[1]])
        diff = diff_bundles(before, after)
        entry = diff["items"]["changed"][0]
        self.assertEqual(entry["id"], "rent-relief-en")
        self.assertEqual([f["field"] for f in entry["fields"]],
                         ["expected", "load_bearing"])
        self.assertEqual(entry["fields"][1], {"field": "load_bearing",
                                              "from": False, "to": True})

    def test_sources_are_compared_too(self):
        src = {"id": "s1", "text": "The maximum award is 850 dollars.",
               "title": "Rent relief"}
        before = self._bundle("before", sources=[src])
        edited = dict(src, text="The maximum award is 900 dollars.")
        after = self._bundle("after", sources=[edited, {"id": "s2", "text": "New."}])
        diff = diff_bundles(before, after)
        self.assertEqual(diff["sources"]["added"], ["s2"])
        self.assertEqual([c["id"] for c in diff["sources"]["changed"]], ["s1"])

    def test_a_manifest_change_is_reported_as_one(self):
        before = self._bundle("before")
        after = self._bundle("after")
        (after / "manifest.json").write_text(
            json.dumps({**json.loads((after / "manifest.json").read_text()),
                        "version": "0.0.2"}, indent=2) + "\n", encoding="utf-8")
        from plumbline.bundle import seal
        seal(after)
        diff = diff_bundles(before, after)
        keys = [e["key"] for e in diff["manifest"]["changed"]]
        self.assertIn("version", keys)
        self.assertIn("manifest: version", "\n".join(summarize_for_terminal(diff)))

    # --- what it refuses to say --------------------------------------------

    def test_formatting_only_is_not_reported_as_a_changed_answer(self):
        """`normalize` is what the judges score through. A response that differs
        only in punctuation is a different string and the same answer, and
        calling it "changed" sends a reader hunting for nothing."""
        before = self._bundle("before")
        after = self._bundle(
            "after",
            responses=[response("rent-relief-en", "The maximum award is 850 dollars!!"),
                       _responses()[1]])
        diff = diff_bundles(before, after)
        entry = diff["responses"]["changed"][0]
        self.assertFalse(entry["text_changed"])
        self.assertEqual(entry["numbers_added"], [])
        self.assertEqual(entry["numbers_removed"], [])
        self.assertIn("formatting only",
                      "\n".join(summarize_for_terminal(diff)))

    def test_the_same_fee_written_two_ways_is_not_a_moved_number(self):
        """`$125.00` and `$125` are the same fee; `extract_numbers` says so, and
        a diff that disagreed would report a formatting edit as a fabrication."""
        before = self._bundle(
            "before", responses=[response("rent-relief-en", "The fee is 125.00 dollars."),
                                 _responses()[1]])
        after = self._bundle(
            "after", responses=[response("rent-relief-en", "The fee is 125 dollars."),
                                _responses()[1]])
        diff = diff_bundles(before, after)
        entry = diff["responses"]["changed"][0]
        self.assertEqual(entry["numbers_added"], [])
        self.assertEqual(entry["numbers_removed"], [])

    # --- fail closed --------------------------------------------------------

    def test_an_unsealed_bundle_is_refused_rather_than_diffed(self):
        good = self._bundle("good")
        unsealed = self._bundle("unsealed", do_seal=False)
        with self.assertRaises(IntegrityError):
            diff_bundles(good, unsealed)
        with self.assertRaises(IntegrityError):
            diff_bundles(unsealed, good)

    def test_a_tampered_bundle_is_refused_rather_than_diffed(self):
        good = self._bundle("good")
        tampered = self._bundle("tampered")
        path = tampered / "responses.jsonl"
        path.write_text(path.read_text(encoding="utf-8").replace("850", "900"),
                        encoding="utf-8")
        with self.assertRaises(IntegrityError):
            diff_bundles(good, tampered)

    # --- the property that keeps the comparison complete --------------------

    def test_every_item_field_is_compared(self):
        """The field list is derived from the dataclass, not written out. A
        field added to `Item` and forgotten here would be a difference the diff
        silently did not look for -- the same shape as a scan whose root list
        went stale. This asserts the derivation rather than the list."""
        from plumbline import diff as diff_mod
        compared = {f.name for f in dataclasses.fields(Item)} - {"id"}
        before = self._bundle("before")
        for name in sorted(compared):
            with self.subTest(field=name):
                a = diff_mod._fields(Item(id="x", lang="en", behavior="answer",
                                          prompt="p"), "id")
                self.assertIn(name, a)
        # And `id` is the key, so it is never reported as a changed field.
        self.assertNotIn("id", diff_mod._fields(
            Item(id="x", lang="en", behavior="answer", prompt="p"), "id"))
        del before


class TheCliVerb(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.before = write_bundle(self.root, _items(), _responses(), name="before")
        self.after = write_bundle(self.root, _items(), _responses("900"), name="after")

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_identical_bundles_exit_zero_and_say_nothing_changed(self):
        code, out, _ = self._run(["diff", str(self.before), str(self.before)])
        self.assertEqual(code, 0)
        self.assertIn("no difference", out)

    def test_a_difference_alone_is_not_a_failure(self):
        code, out, _ = self._run(["diff", str(self.before), str(self.after)])
        self.assertEqual(code, 0)
        self.assertIn("850", out)
        self.assertIn("900", out)

    def test_fail_on_change_exits_one_when_they_differ(self):
        code, _, _ = self._run(
            ["diff", str(self.before), str(self.after), "--fail-on-change"])
        self.assertEqual(code, 1)

    def test_fail_on_change_exits_zero_when_they_do_not(self):
        code, _, _ = self._run(
            ["diff", str(self.before), str(self.before), "--fail-on-change"])
        self.assertEqual(code, 0)

    def test_json_output_is_parseable_and_ordered(self):
        code, out, _ = self._run(["diff", str(self.before), str(self.after), "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["format"], "plumbline-bundle-diff")
        self.assertTrue(parsed["changed"])
        again = self._run(["diff", str(self.before), str(self.after), "--json"])[1]
        self.assertEqual(out, again, "the diff must be deterministic")

    def test_a_missing_checksums_file_is_the_integrity_exit_code(self):
        unsealed = write_bundle(self.root, _items(), _responses(),
                                name="unsealed", do_seal=False)
        code, _, err = self._run(["diff", str(self.before), str(unsealed)])
        self.assertEqual(code, 3, err)
        self.assertIn("INTEGRITY REFUSAL", err)


class TheDiffCanFail(unittest.TestCase):
    """Negative controls. Each plants the fault the check above exists to
    catch, and requires the check to notice. A diff that reported nothing would
    satisfy every assertion in `DiffTests` that looks for an empty list."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_a_changed_response_is_not_reported_as_no_difference(self):
        before = write_bundle(self.root, _items(), _responses(), name="b")
        after = write_bundle(self.root, _items(), _responses("900"), name="a")
        diff = diff_bundles(before, after)
        self.assertTrue(diff["changed"])
        self.assertNotIn("no difference", "\n".join(summarize_for_terminal(diff)))

    def test_every_recorded_difference_reaches_the_printed_lines(self):
        """A section counted in `changed` and rendered nowhere is a change
        reported as nothing having happened."""
        before = write_bundle(self.root, _items(), _responses(), name="b")
        after = write_bundle(
            self.root,
            [answer_item("rent-relief-en", "The maximum award is 900 dollars."),
             answer_item("new-en", "Another.")],
            [response("rent-relief-en", "The maximum award is 900 dollars."),
             response("new-en", "Another.")],
            name="a")
        diff = diff_bundles(before, after)
        text = "\n".join(summarize_for_terminal(diff))
        for ident in (diff["items"]["added"] + diff["items"]["removed"]
                      + diff["responses"]["added"] + diff["responses"]["removed"]
                      + [c["id"] for c in diff["items"]["changed"]]
                      + [c["id"] for c in diff["responses"]["changed"]]):
            self.assertIn(ident, text, f"{ident} is in the diff and not in the summary")


if __name__ == "__main__":
    unittest.main()
