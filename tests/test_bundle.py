import tempfile
import unittest
from pathlib import Path

from plumbline.bundle import BundleError, IntegrityError, load, seal, verify_integrity

from helpers import answer_item, refuse_item, response, write_bundle


def _basic_items():
    return [
        answer_item("a1", "The fee is 25 dollars."),
        refuse_item("r1"),
    ]


def _basic_responses():
    return [
        response("a1", "The fee is 25 dollars."),
        response("r1", "I can't help with that."),
    ]


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_sealed_bundle_loads(self):
        bundle_dir = write_bundle(self.root, _basic_items(), _basic_responses())
        bundle = load(bundle_dir)
        self.assertEqual(len(bundle.items), 2)
        self.assertEqual(bundle.response_for("a1"), "The fee is 25 dollars.")
        self.assertEqual(len(bundle.dataset_sha256), 64)
        self.assertEqual(bundle.dataset_id, bundle.dataset_sha256[:12])

    def test_tampered_response_refuses(self):
        bundle_dir = write_bundle(self.root, _basic_items(), _basic_responses())
        path = bundle_dir / "responses.jsonl"
        path.write_text(path.read_text().replace("25", "40"), encoding="utf-8")
        with self.assertRaises(IntegrityError):
            load(bundle_dir)

    def test_tampered_items_refuses(self):
        bundle_dir = write_bundle(self.root, _basic_items(), _basic_responses())
        path = bundle_dir / "items.jsonl"
        path.write_text(path.read_text().replace("25", "40"), encoding="utf-8")
        with self.assertRaises(IntegrityError):
            verify_integrity(bundle_dir)

    def test_missing_checksums_refuses(self):
        bundle_dir = write_bundle(
            self.root, _basic_items(), _basic_responses(), do_seal=False
        )
        with self.assertRaises(IntegrityError):
            load(bundle_dir)

    def test_unlisted_extra_file_refuses(self):
        bundle_dir = write_bundle(self.root, _basic_items(), _basic_responses())
        (bundle_dir / "extra.txt").write_text("smuggled", encoding="utf-8")
        with self.assertRaises(IntegrityError):
            load(bundle_dir)

    def test_reseal_after_edit_restores_loadability_with_new_hash(self):
        bundle_dir = write_bundle(self.root, _basic_items(), _basic_responses())
        old_hash = load(bundle_dir).dataset_sha256
        path = bundle_dir / "responses.jsonl"
        path.write_text(path.read_text().replace("25", "40"), encoding="utf-8")
        seal(bundle_dir)  # legitimate regeneration
        new_hash = load(bundle_dir).dataset_sha256
        self.assertNotEqual(old_hash, new_hash)  # the trace


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_duplicate_item_id_rejected(self):
        items = [answer_item("dup", "x"), answer_item("dup", "y")]
        bundle_dir = write_bundle(self.root, items, [response("dup", "x")])
        with self.assertRaises(BundleError):
            load(bundle_dir)

    def test_answer_item_requires_expected(self):
        items = [{"id": "a1", "lang": "en", "behavior": "answer", "prompt": "p"}]
        bundle_dir = write_bundle(self.root, items, [])
        with self.assertRaises(BundleError):
            load(bundle_dir)

    def test_unknown_behavior_rejected(self):
        items = [{"id": "a1", "lang": "en", "behavior": "muse", "prompt": "p"}]
        bundle_dir = write_bundle(self.root, items, [])
        with self.assertRaises(BundleError):
            load(bundle_dir)

    def test_response_for_unknown_item_rejected(self):
        bundle_dir = write_bundle(
            self.root, _basic_items(),
            _basic_responses() + [response("ghost", "boo")],
        )
        with self.assertRaises(BundleError):
            load(bundle_dir)

    def test_unreviewed_translation_warning_collected(self):
        items = [
            answer_item("a1", "The fee is 25 dollars."),
            answer_item(
                "a2", "La tarifa es de 25 dólares.",
                translation={"of": "a1", "review": "unreviewed"},
            ),
        ]
        responses = [response("a1", "x"), response("a2", "y")]
        bundle = load(write_bundle(self.root, items, responses))
        warnings = bundle.unreviewed_translation_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn("a2", warnings[0])
        self.assertIn("subject-matter-expert review", warnings[0])

    def test_reviewed_translation_no_warning(self):
        items = [
            answer_item("a1", "The fee is 25 dollars."),
            answer_item(
                "a2", "La tarifa es de 25 dólares.",
                translation={"of": "a1", "review": "sme_reviewed"},
            ),
        ]
        responses = [response("a1", "x"), response("a2", "y")]
        bundle = load(write_bundle(self.root, items, responses))
        self.assertEqual(bundle.unreviewed_translation_warnings(), [])


class AnsweringSourceDeclarationTests(unittest.TestCase):
    """`answering_sources`: which passage actually answers the question.

    Opt-in, and unusable unless it resolves — a declaration nobody can read
    would have the attribution suite grading answers against nothing.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.sources = [
            {"id": "s-eligibility", "text": "Eligibility depends on household income."},
            {"id": "s-fare", "text": "The household fare is 2 dollars per ride."},
        ]

    def _load(self, **extra):
        items = [answer_item("a1", "Eligibility depends on household income.",
                             sources=["s-eligibility", "s-fare"], **extra)]
        return load(write_bundle(self.root, items, [response("a1", "x")],
                                 sources=self.sources))

    def test_absent_by_default(self):
        bundle = self._load()
        self.assertEqual(bundle.items[0].answering_sources, [])
        self.assertEqual(bundle.distractor_sources_for(bundle.items[0]),
                         list(bundle.sources_for(bundle.items[0])))

    def test_declared_passages_resolve(self):
        bundle = self._load(answering_sources=["s-eligibility"])
        item = bundle.items[0]
        self.assertEqual([s.id for s in bundle.answering_sources_for(item)],
                         ["s-eligibility"])
        self.assertEqual([s.id for s in bundle.distractor_sources_for(item)],
                         ["s-fare"])

    def test_a_declaration_outside_the_corpus_is_a_bundle_error(self):
        with self.assertRaises(BundleError) as caught:
            self._load(answering_sources=["s-nowhere"])
        self.assertIn("answering_sources that are not in the corpus",
                      str(caught.exception))

    def test_an_empty_declaration_is_a_bundle_error(self):
        with self.assertRaises(BundleError) as caught:
            self._load(answering_sources=[])
        self.assertIn("empty 'answering_sources'", str(caught.exception))

    def test_a_declaration_that_is_not_a_list_of_ids_is_a_bundle_error(self):
        with self.assertRaises(BundleError) as caught:
            self._load(answering_sources="s-eligibility")
        self.assertIn("must be a list of source ids", str(caught.exception))

    def test_a_refusal_item_may_not_declare_one(self):
        items = [refuse_item("r1")]
        items[0]["answering_sources"] = ["s-fare"]
        with self.assertRaises(BundleError) as caught:
            load(write_bundle(self.root, items, [response("r1", "no")],
                              sources=self.sources))
        self.assertIn("Nothing answers a question that should not be answered",
                      str(caught.exception))

    def test_a_declaration_need_not_have_been_retrieved(self):
        # Not an error: the passage that answers the question existing and
        # never reaching the target is a retrieval failure the attribution
        # suite reports, not a malformed bundle.
        items = [answer_item("a1", "Eligibility depends on household income.",
                             sources=["s-fare"],
                             answering_sources=["s-eligibility"])]
        bundle = load(write_bundle(self.root, items, [response("a1", "x")],
                                   sources=self.sources))
        item = bundle.items[0]
        self.assertEqual([s.id for s in bundle.answering_sources_for(item)],
                         ["s-eligibility"])
        self.assertEqual([s.id for s in bundle.distractor_sources_for(item)],
                         ["s-fare"])


if __name__ == "__main__":
    unittest.main()
