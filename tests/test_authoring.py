"""`plumbline author` and `plumbline suggest-declarations`.

The property the whole file is arranged around: a **draft** item is exempt
from the two blank-content refusals in `bundle._parse_items`, and that
exemption is only safe if every path that could score a draft or send one to
a live target refuses it first. So the tests come in pairs — the exemption
exists, and the refusal that makes it safe fires.

The failure this guards against is the one this repository catalogues
everywhere else: a blank reference answer scored as though it were content
makes an empty response look like a perfect match, and a blank prompt sent to
a live target files the answer to a question nobody asked.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import answer_item, response, run_cli, write_bundle

from plumbline import bundle as bundle_mod
from plumbline.authoring import (
    AuthoringUsageError,
    NO_REFERENCE_ANSWER,
    NOT_COMPUTED,
    SINGLE_CANDIDATE,
    UNDETERMINED,
    render_sheet,
    suggestions_for,
    write_question_set,
)
from plumbline.bundle import BundleError, load_questions
from plumbline.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_USAGE
from plumbline.judges import make_judge

CONFIG_TEMPLATE = """
[target]
name = "draft-target"

[dataset]
path = "{dataset_path}"

[suites.smoke]
floor = 1.0
"""

CORPUS = [
    {"id": "src-a", "title": "Payment cap", "url": "https://x.example/a",
     "text": "The programme pays a maximum of 850 dollars per month toward "
             "rent for an eligible household."},
    {"id": "src-b", "title": "Office hours",
     "text": "The benefits office is open Monday through Friday from nine "
             "in the morning until four in the afternoon."},
]


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def corpus_file(self, records=CORPUS) -> Path:
        path = self.root / "sources.jsonl"
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8")
        return path


class Author(TempCase):
    def test_one_draft_item_per_passage_per_language(self):
        write_question_set(sources_path=self.corpus_file(),
                           out_dir=self.root / "qs",
                           languages=["en", "es"], name="drafted")
        bundle = load_questions(self.root / "qs")
        self.assertEqual(len(bundle.items), 4)
        self.assertEqual(sorted(i.id for i in bundle.items),
                         ["src-a-en", "src-a-es", "src-b-en", "src-b-es"])
        for item in bundle.items:
            self.assertEqual(item.review, bundle_mod.ITEM_REVIEW_DRAFT)
            self.assertEqual(item.prompt, "")
            self.assertEqual(item.expected, "")
            self.assertEqual(item.behavior, "answer")

    def test_the_drafted_passage_is_prefilled_as_the_answering_source(self):
        write_question_set(sources_path=self.corpus_file(),
                           out_dir=self.root / "qs", languages=["en"],
                           name="drafted")
        bundle = load_questions(self.root / "qs")
        for item in bundle.items:
            self.assertEqual(item.sources, item.answering_sources)
            self.assertEqual(len(item.answering_sources), 1)

    def test_languages_from_one_passage_share_a_fact_id_and_link_as_translations(self):
        write_question_set(sources_path=self.corpus_file(),
                           out_dir=self.root / "qs",
                           languages=["en", "es"], name="drafted")
        by_id = {i.id: i for i in load_questions(self.root / "qs").items}
        self.assertEqual(by_id["src-a-en"].fact_id, by_id["src-a-es"].fact_id)
        self.assertNotEqual(by_id["src-a-en"].fact_id, by_id["src-b-en"].fact_id)
        # The primary language is the first one given, and it is nobody's
        # translation.
        self.assertIsNone(by_id["src-a-en"].translation)
        self.assertEqual(by_id["src-a-es"].translation,
                         {"of": "src-a-en", "review": "unreviewed"})

    def test_the_drafted_set_is_sealed_and_validates(self):
        write_question_set(sources_path=self.corpus_file(),
                           out_dir=self.root / "qs", languages=["en"],
                           name="drafted")
        self.assertTrue((self.root / "qs" / "checksums.json").is_file())
        code, out, _ = run_cli("validate", str(self.root / "qs"))
        self.assertEqual(code, EXIT_PASS)
        self.assertIn("integrity: OK", out)

    def test_drafting_twice_produces_byte_identical_output(self):
        corpus = self.corpus_file()
        first = write_question_set(sources_path=corpus,
                                   out_dir=self.root / "one",
                                   languages=["en", "es"], name="drafted")
        second = write_question_set(sources_path=corpus,
                                    out_dir=self.root / "two",
                                    languages=["en", "es"], name="drafted")
        self.assertEqual(first["bundle_sha256"], second["bundle_sha256"])
        for filename in ("items.jsonl", "sources.jsonl", "manifest.json"):
            self.assertEqual(
                (self.root / "one" / filename).read_bytes(),
                (self.root / "two" / filename).read_bytes(), filename)

    def test_an_empty_corpus_is_a_usage_error(self):
        empty = self.root / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        with self.assertRaises(AuthoringUsageError) as caught:
            write_question_set(sources_path=empty, out_dir=self.root / "qs",
                               languages=["en"], name="drafted")
        self.assertIn("no passages", str(caught.exception))
        # And nothing was written: an empty question set is not left behind
        # for someone to seal by hand.
        self.assertFalse((self.root / "qs" / "items.jsonl").exists())

    def test_the_cli_reports_an_empty_corpus_as_exit_two(self):
        empty = self.root / "empty.jsonl"
        empty.write_text("\n\n", encoding="utf-8")
        code, _, err = run_cli("author", "--sources", str(empty),
                               "--out", str(self.root / "qs"))
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("USAGE ERROR", err)

    def test_a_repeated_language_is_a_usage_error(self):
        with self.assertRaises(AuthoringUsageError) as caught:
            write_question_set(sources_path=self.corpus_file(),
                               out_dir=self.root / "qs",
                               languages=["en", "en"], name="drafted")
        self.assertIn("more than once", str(caught.exception))

    def test_drafting_into_a_non_empty_directory_is_refused(self):
        target = self.root / "qs"
        target.mkdir()
        (target / "items.jsonl").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(AuthoringUsageError):
            write_question_set(sources_path=self.corpus_file(),
                               out_dir=target, languages=["en"],
                               name="drafted")

    def test_the_cli_defaults_to_english_without_appending_to_it(self):
        code, out, _ = run_cli("author", "--sources", str(self.corpus_file()),
                               "--out", str(self.root / "qs"), "--lang", "es")
        self.assertEqual(code, EXIT_PASS)
        langs = {i.lang for i in load_questions(self.root / "qs").items}
        self.assertEqual(langs, {"es"})
        self.assertIn("draft items across es", out)


class DraftsAreExemptAndThenRefused(TempCase):
    """The exemption, and each refusal that makes it safe."""

    def _bundle(self, *, review):
        item = answer_item("a1", "")
        item["prompt"] = ""
        if review is not None:
            item["review"] = review
        return write_bundle(self.root, [item], [response("a1", "anything")],
                            name=f"b-{review or 'none'}")

    def test_a_draft_may_carry_a_blank_prompt_and_expected(self):
        bundle = load_questions(self._bundle(review="draft"))
        self.assertEqual(bundle.draft_item_ids(), ["a1"])

    def test_the_same_item_without_the_marker_is_a_bundle_error(self):
        with self.assertRaises(BundleError) as caught:
            load_questions(self._bundle(review=None))
        self.assertIn("blank prompt", str(caught.exception))

    def test_an_unknown_review_value_is_refused_rather_than_ignored(self):
        with self.assertRaises(BundleError) as caught:
            self._bundle(review="drfat")
            load_questions(self.root / "b-drfat")
        self.assertIn("review=", str(caught.exception))

    def test_a_blank_expected_alone_is_still_refused_without_the_marker(self):
        item = answer_item("a1", "   ")
        path = write_bundle(self.root, [item], [response("a1", "x")],
                            name="blank-expected")
        with self.assertRaises(BundleError) as caught:
            load_questions(path)
        self.assertIn("no expected answer", str(caught.exception))

    def test_audit_refuses_a_bundle_that_still_holds_a_draft(self):
        item = answer_item("a1", "")
        item["prompt"] = ""
        item["review"] = "draft"
        bundle_dir = write_bundle(
            self.root, [item, answer_item("a2", "offices open on monday")],
            [response("a1", "x"), response("a2", "offices open on monday")],
            name="mixed")
        config = self.root / "target.toml"
        config.write_text(CONFIG_TEMPLATE.format(dataset_path=str(bundle_dir)),
                          encoding="utf-8")
        code, _, err = run_cli("audit", "--config", str(config),
                               "--out", str(self.root / "audits"))
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn('review = "draft"', err)
        self.assertIn("a1", err)
        # Nothing was scored: no report directory was written.
        self.assertFalse((self.root / "audits").exists())

    def test_record_refuses_a_question_set_that_still_holds_a_draft(self):
        from plumbline.recording import record

        write_question_set(sources_path=self.corpus_file(),
                           out_dir=self.root / "qs", languages=["en"],
                           name="drafted")
        questions = load_questions(self.root / "qs")

        class ExplodingAdapter:
            kind = "never-called"

            def respond(self, item):  # pragma: no cover - must not be reached
                raise AssertionError("a draft item reached the adapter")

        with self.assertRaises(BundleError) as caught:
            record(questions=questions, adapter=ExplodingAdapter(),
                   out_dir=self.root / "recorded")
        self.assertIn('review = "draft"', str(caught.exception))
        self.assertFalse((self.root / "recorded").exists())

    def test_validate_reports_drafts_rather_than_refusing_them(self):
        write_question_set(sources_path=self.corpus_file(),
                           out_dir=self.root / "qs", languages=["en"],
                           name="drafted")
        code, out, _ = run_cli("validate", str(self.root / "qs"))
        self.assertEqual(code, EXIT_PASS)
        self.assertIn("drafts:", out)
        self.assertIn("2 item(s)", out)

    def test_clearing_the_marker_is_what_makes_the_bundle_usable(self):
        """The whole loop, end to end: draft, fill in, clear, score."""
        write_question_set(sources_path=self.corpus_file(),
                           out_dir=self.root / "qs", languages=["en"],
                           name="drafted")
        items_path = self.root / "qs" / "items.jsonl"
        filled = []
        for line in items_path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            raw["prompt"] = f"question about {raw['sources'][0]}"
            raw["expected"] = "the programme pays 850 dollars"
            del raw["review"]
            filled.append(raw)
        items_path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in filled),
            encoding="utf-8")
        # Editing the evidence breaks the seal, exactly as it should.
        code, _, _ = run_cli("seal", str(self.root / "qs"))
        self.assertEqual(code, EXIT_PASS)
        bundle = load_questions(self.root / "qs")
        self.assertEqual(bundle.draft_item_ids(), [])
        bundle_mod.refuse_drafts(bundle, "scored")  # no longer raises


class SuggestDeclarations(TempCase):
    def setUp(self):
        super().setUp()
        self.judge, _ = make_judge({"kind": "lexical"}, offline_only=True)

    def _bundle(self, items, sources=CORPUS):
        return write_bundle(
            self.root, items, [response(i["id"], "x") for i in items],
            name="suggest", sources=sources)

    def test_a_clear_winner_is_named(self):
        item = answer_item(
            "a1", "the programme pays a maximum of 850 dollars per month "
                  "toward rent for an eligible household",
            sources=["src-a", "src-b"])
        bundle = load_questions(self._bundle([item]))
        rows = suggestions_for(bundle, self.judge)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].suggestion, "src-a")
        self.assertTrue(rows[0].is_declaration)
        self.assertGreaterEqual(rows[0].margin, 0.1)

    def test_a_reference_answer_inside_the_margin_is_undetermined(self):
        # Two passages that say the same thing in different words. Neither
        # accounts for the reference answer better than the other, so no
        # passage is named -- which is the point: this is where a suggestion
        # would be a guess dressed as a finding.
        twins = CORPUS + [
            {"id": "src-twin-1",
             "text": "Applications must be submitted before the fifteenth "
                     "of the month to be considered in that cycle."},
            {"id": "src-twin-2",
             "text": "Applications must be submitted before the fifteenth "
                     "of the month to be considered in that cycle."},
        ]
        item = answer_item(
            "a1", "applications must be submitted before the fifteenth of "
                  "the month",
            sources=["src-twin-1", "src-twin-2"])
        bundle = load_questions(self._bundle([item], sources=twins))
        rows = suggestions_for(bundle, self.judge)
        self.assertEqual(rows[0].suggestion, UNDETERMINED)
        self.assertFalse(rows[0].is_declaration)
        self.assertLess(rows[0].margin, 0.1)
        # And the sheet says so in words rather than leaving a blank cell.
        self.assertIn("| undetermined |", render_sheet(bundle, rows))

    def test_every_undeclared_item_gets_a_row_even_when_nothing_is_comparable(self):
        items = [
            answer_item("a1", "the programme pays 850 dollars",
                        sources=["src-a"]),                    # one candidate
            answer_item("a2", "offices open monday",
                        sources=["src-a", "src-b"]),           # comparable
        ]
        bundle = load_questions(self._bundle(items))
        rows = suggestions_for(bundle, self.judge)
        self.assertEqual([r.item_id for r in rows], ["a1", "a2"])
        self.assertEqual(rows[0].suggestion, SINGLE_CANDIDATE)
        self.assertIsNone(rows[0].margin)

    def test_a_row_that_compared_nothing_does_not_publish_a_margin_of_zero(self):
        item = answer_item("a1", "the programme pays 850 dollars",
                           sources=["src-a"])
        bundle = load_questions(self._bundle([item]))
        sheet = render_sheet(bundle, suggestions_for(bundle, self.judge))
        rows = [line for line in sheet.splitlines() if line.startswith("| `a1`")]
        self.assertEqual(len(rows), 1, sheet)
        self.assertIn(NOT_COMPUTED, rows[0])
        # A zero margin is a measured tie between two passages. This item had
        # one passage, so it measured nothing, and the row must not read as a
        # tie. (The legend below the table explains the distinction and
        # mentions `0.0000`; the assertion is scoped to the row on purpose.)
        self.assertNotIn("0.0000", rows[0])

    def test_an_item_that_already_declares_is_not_listed(self):
        item = answer_item("a1", "the programme pays 850 dollars",
                           sources=["src-a", "src-b"],
                           answering_sources=["src-a"])
        bundle = load_questions(self._bundle([item]))
        self.assertEqual(suggestions_for(bundle, self.judge), [])
        sheet = render_sheet(bundle, [])
        self.assertIn("There is nothing to review", sheet)

    def test_the_sheet_is_byte_identical_across_runs(self):
        items = [answer_item("a1", "the programme pays 850 dollars",
                             sources=["src-a", "src-b"]),
                 answer_item("a2", "offices open monday to friday",
                             sources=["src-a", "src-b"])]
        bundle = load_questions(self._bundle(items))
        first = render_sheet(bundle, suggestions_for(bundle, self.judge))
        second = render_sheet(bundle, suggestions_for(bundle, self.judge))
        self.assertEqual(first, second)

    def test_the_cli_writes_the_sheet_and_leaves_the_bundle_alone(self):
        item = answer_item("a1", "the programme pays 850 dollars",
                           sources=["src-a", "src-b"])
        bundle_dir = self._bundle([item])
        before = (bundle_dir / "items.jsonl").read_bytes()
        out = self.root / "sheet.md"
        code, stdout, _ = run_cli("suggest-declarations", str(bundle_dir),
                                  "--out", str(out))
        self.assertEqual(code, EXIT_PASS)
        self.assertIn("nothing was written into the bundle", stdout)
        self.assertIn("Suggested `answering_sources` declarations",
                      out.read_text(encoding="utf-8"))
        self.assertEqual((bundle_dir / "items.jsonl").read_bytes(), before)

    def test_a_draft_item_with_no_reference_answer_is_named_as_such(self):
        write_question_set(sources_path=self.corpus_file(),
                           out_dir=self.root / "qs", languages=["en"],
                           name="drafted")
        # Strip the prefilled declaration so the drafts show up as undeclared.
        items_path = self.root / "qs" / "items.jsonl"
        stripped = []
        for line in items_path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            del raw["answering_sources"]
            raw["sources"] = ["src-a", "src-b"]
            stripped.append(raw)
        items_path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in stripped),
            encoding="utf-8")
        run_cli("seal", str(self.root / "qs"))
        bundle = load_questions(self.root / "qs")
        rows = suggestions_for(bundle, self.judge)
        self.assertTrue(rows)
        self.assertTrue(all(r.suggestion == NO_REFERENCE_ANSWER for r in rows))
        self.assertTrue(all(r.margin is None for r in rows))


if __name__ == "__main__":
    unittest.main()
