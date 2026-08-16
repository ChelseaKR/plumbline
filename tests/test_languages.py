"""Language identification: shipped scripts, declared profiles, and the two
constraints that make a naive word list the wrong answer for Arabic.

A consuming service that answers in a language Plumbline has never heard of
must be able to score the `multilingual` suite rather than declare it
unscored. Declaring it unscored is a silent skip wearing a configuration
setting's clothes, and this harness does not have those.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import response, run_cli, write_bundle

from plumbline import lexicons
from plumbline.bundle import load as load_bundle
from plumbline.judges import LexicalJudge, make_judge, normalize
from plumbline.suites import get as get_suite

ARABIC = "يمكنك تقديم الطلب عبر الإنترنت أو في مكتب المزايا في مقاطعة ريفربند."
ARABIC_DIACRITIZED = "يُمْكِنُكَ تَقْدِيمُ الطَّلَبِ عَبْرَ الإِنْتَرْنِت."
ENGLISH = "The Riverbend benefits office accepts walk-ins from 9 to 4."
SPANISH = "La oficina de beneficios de Riverbend acepta visitas sin cita."


class NormalizationConstraintTests(unittest.TestCase):
    """Constraint 1: the normalizer does not merely strip Arabic diacritics,
    it replaces each one with a space, which shreds the word around it. Any
    profile word carrying a mark is therefore unmatchable — twice over."""

    def test_normalization_shreds_diacritized_arabic(self):
        normalized = normalize(ARABIC_DIACRITIZED)
        self.assertNotIn("َ", normalized)  # FATHA is gone
        # And what is left is not the word: the marks became separators.
        self.assertIn("ي م ك ن ك", normalized)

    def test_a_profile_word_that_cannot_survive_normalization_is_refused(self):
        with self.assertRaises(lexicons.LanguageRulesError) as caught:
            make_judge({"kind": "lexical",
                        "languages": {"ar": {"words": ["فِي", "مِنْ"]}}})
        self.assertIn("do not survive normalization", str(caught.exception))

    def test_undiacriticized_words_are_accepted(self):
        judge, warnings = make_judge(
            {"kind": "lexical", "languages": {"ar": {"words": ["في", "من"]}}})
        self.assertEqual(warnings, [])
        self.assertEqual(judge.detect_language("في مكتب من"), "ar")


class ArabicScriptTests(unittest.TestCase):
    """Constraint 2: a tie resolves to undetermined, which counts as a
    failure. Script is checked first precisely so a correct Arabic answer can
    never land there."""

    def setUp(self):
        self.judge = LexicalJudge()

    def test_arabic_ships_and_is_detected(self):
        self.assertIn("ar", self.judge.supported_languages())
        self.assertEqual(self.judge.detect_language(ARABIC), "ar")

    def test_diacritics_do_not_defeat_detection(self):
        self.assertEqual(self.judge.detect_language(ARABIC_DIACRITIZED), "ar")

    def test_arabic_does_not_collide_with_the_latin_profiles(self):
        # The failure the reporter warned about: a correct Arabic answer
        # scoring `undetermined` because it tied with en or es.
        self.assertIsNotNone(self.judge.detect_language(ARABIC))

    def test_latin_languages_are_unaffected(self):
        self.assertEqual(self.judge.detect_language(ENGLISH), "en")
        self.assertEqual(self.judge.detect_language(SPANISH), "es")

    def test_a_quoted_latin_phrase_does_not_flip_an_arabic_answer(self):
        mixed = ARABIC + " Riverbend Rent Relief"
        self.assertEqual(self.judge.detect_language(mixed), "ar")

    def test_a_mostly_english_answer_with_one_arabic_word_is_english(self):
        self.assertEqual(
            self.judge.detect_language(ENGLISH + " مكتب"), "en")

    def test_arabic_indic_digits_alone_say_nothing(self):
        # Digits sit inside the Arabic block but are not letters; a response
        # of nothing but numerals is undetermined, not Arabic.
        self.assertIsNone(self.judge.detect_language("٨٥٠ ٢٤٠٠"))


class DeclaredLanguageTests(unittest.TestCase):
    """`[judge.languages]`: the general answer, for the language after the
    next one."""

    def test_a_declared_script_language_is_detected(self):
        judge, _ = make_judge({"kind": "lexical",
                               "languages": {"el": {"script": ["0370-03FF"]}}})
        self.assertIn("el", judge.supported_languages())
        self.assertEqual(
            judge.detect_language("Το γραφείο παροχών είναι ανοιχτό."), "el")

    def test_a_declared_word_profile_is_detected(self):
        judge, _ = make_judge({
            "kind": "lexical",
            "languages": {"pt": {"words": ["voce", "pedido", "beneficios"]}}})
        self.assertEqual(judge.detect_language("voce pedido beneficios"), "pt")

    def test_declaring_a_tag_replaces_the_shipped_profile_for_it(self):
        judge, _ = make_judge({"kind": "lexical",
                               "languages": {"en": {"words": ["zzz"]}}})
        self.assertEqual(judge.detect_language("zzz"), "en")
        self.assertNotEqual(judge.detect_language(ENGLISH), "en")

    def test_shared_words_warn_and_do_not_refuse(self):
        judge, warnings = make_judge({
            "kind": "lexical",
            "languages": {"pt": {"words": ["de", "que", "para"]}}})
        self.assertTrue(any("share the word" in w for w in warnings))
        self.assertIn("pt", judge.supported_languages())

    def test_an_entry_with_neither_words_nor_script_is_refused(self):
        with self.assertRaises(lexicons.LanguageRulesError):
            make_judge({"kind": "lexical", "languages": {"pt": {}}})

    def test_an_unknown_key_in_a_declaration_is_refused(self):
        with self.assertRaises(lexicons.LanguageRulesError) as caught:
            make_judge({"kind": "lexical",
                        "languages": {"pt": {"wordlist": ["de"]}}})
        self.assertIn("Refused rather than ignored", str(caught.exception))

    def test_a_malformed_script_range_is_refused(self):
        with self.assertRaises(lexicons.LanguageRulesError):
            make_judge({"kind": "lexical",
                        "languages": {"el": {"script": ["greek"]}}})

    def test_a_backwards_script_range_is_refused(self):
        with self.assertRaises(lexicons.LanguageRulesError):
            make_judge({"kind": "lexical",
                        "languages": {"el": {"script": ["03FF-0370"]}}})

    def test_language_rules_are_inside_the_judge_configuration_hash(self):
        plain, _ = make_judge({"kind": "lexical"})
        declared, _ = make_judge({"kind": "lexical",
                                  "languages": {"el": {"script": ["0370-03FF"]}}})
        self.assertNotEqual(plain.config_hash(), declared.config_hash())
        self.assertNotIn("el", plain.config()["lexicons"]["languages"])
        self.assertIn("el", declared.config()["lexicons"]["languages"])


class MultilingualSuiteWithArabicTests(unittest.TestCase):
    """End to end: a bundle with Arabic items scores rather than raising."""

    ITEMS = [
        {"id": "a-1", "lang": "en", "behavior": "answer",
         "prompt": "When is the office open?",
         "expected": "The office is open from 9 to 4."},
        {"id": "a-2", "lang": "ar", "behavior": "answer",
         "prompt": "متى يفتح المكتب؟",
         "expected": "المكتب مفتوح من الساعة ٩ حتى الساعة ٤."},
    ]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _bundle(self, arabic_response):
        path = write_bundle(self.root, self.ITEMS, [
            response("a-1", "The office is open from 9 to 4."),
            response("a-2", arabic_response),
        ])
        return load_bundle(path)

    def test_an_arabic_answer_to_an_arabic_question_scores_one(self):
        bundle = self._bundle("المكتب مفتوح من الساعة التاسعة حتى الرابعة.")
        result = get_suite("multilingual").evaluate(bundle, LexicalJudge(), 0.95)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.verdict, "PASS")

    def test_an_english_answer_to_an_arabic_question_fails_the_item(self):
        bundle = self._bundle("The office is open from 9 to 4.")
        result = get_suite("multilingual").evaluate(bundle, LexicalJudge(), 0.95)
        self.assertEqual(result.score, 0.5)
        self.assertEqual(result.details["language_mismatches"], ["a-2"])

    def test_an_undeclared_language_still_refuses_rather_than_passing(self):
        items = [dict(self.ITEMS[0]),
                 {"id": "a-3", "lang": "ja", "behavior": "answer",
                  "prompt": "いつ開いていますか", "expected": "9時から4時まで"}]
        path = write_bundle(self.root, items, [
            response("a-1", "The office is open."),
            response("a-3", "9時から4時まで開いています。"),
        ], name="ja-bundle")
        bundle = load_bundle(path)
        with self.assertRaises(ValueError) as caught:
            get_suite("multilingual").evaluate(bundle, LexicalJudge(), 0.95)
        self.assertIn("[judge.languages.ja]", str(caught.exception))


class DeclaredLanguageThroughTheCLITests(unittest.TestCase):
    """The whole path: a TOML target config declaring a language, audited."""

    def test_a_declared_language_audits_and_is_named_in_the_report(self):
        items = [
            {"id": "g-1", "lang": "en", "behavior": "answer",
             "prompt": "Is the office open?", "expected": "The office is open."},
            {"id": "g-2", "lang": "el", "behavior": "answer",
             "prompt": "Είναι ανοιχτό το γραφείο;",
             "expected": "Το γραφείο είναι ανοιχτό."},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_bundle(root, items, [
                response("g-1", "The office is open."),
                response("g-2", "Το γραφείο είναι ανοιχτό."),
            ])
            config = root / "target.toml"
            config.write_text(
                "[target]\nname = \"declared\"\n\n"
                f"[dataset]\npath = \"{path}\"\n\n"
                "[judge]\nkind = \"lexical\"\n\n"
                "[judge.languages.el]\nscript = [\"0370-03FF\"]\n\n"
                "[suites.multilingual]\nenabled = true\n",
                encoding="utf-8")
            out = root / "audits"
            code, stdout, _ = run_cli(
                "audit", "--config", str(config), "--out", str(out))
            self._assert_report(code, stdout, out)

    def _assert_report(self, code, stdout, out):
        self.assertEqual(code, 0, stdout)
        report = json.loads(
            next(Path(out).glob("*/report.json")).read_text(encoding="utf-8"))
        languages = report["judge"]["languages"]
        self.assertIn("el", languages)
        self.assertEqual(report["suites"][0]["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
