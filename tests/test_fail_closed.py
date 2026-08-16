"""Gates that cannot fail.

Every test here corresponds to a way a verdict could once come back PASS
because a check did not actually run. A harness whose thesis is "a gate that
could not run is not a gate that passed" contradicts itself the moment one of
these regresses, so they are grouped together rather than scattered through
the suite files: this file is the thesis, executable.

Each class names the shape of the hole. The docstrings say what the behavior
was before, because a regression test whose failure message does not explain
what it is protecting is a puzzle for whoever breaks it.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import answer_item, refuse_item, response, run_cli, write_bundle

from plumbline import bundle as bundle_mod
from plumbline.audit import (
    CoverageError,
    ResultError,
    compute_run_id,
    run_audit,
    run_id_of,
    validate_result,
)
from plumbline.bundle import BundleError, IntegrityError, load, seal, verify_integrity
from plumbline.cli import (
    EXIT_CONFIG_ERROR,
    EXIT_INTEGRITY_REFUSAL,
    EXIT_INTERNAL_ERROR,
    EXIT_PASS,
    EXIT_SUITE_FAILURE,
)
from plumbline.config import ConfigError, load_config
from plumbline.hashing import bundle_digest
from plumbline.judges import LexicalJudge
from plumbline.report import (
    ReportSealError,
    REPORT_SEAL_FIELD,
    report_digest,
    verify_report,
)
from plumbline.suites import FAIL, PASS, SuiteResult, get as get_suite

REPO = Path(__file__).resolve().parent.parent
DEMO_BUNDLE = REPO / "datasets" / "riverbend-demo"


def _items():
    return [answer_item("a1", "The fee is 25 dollars."), refuse_item("r1")]


def _responses():
    return [response("a1", "The fee is 25 dollars."),
            response("r1", "I can't help with that.")]


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write_config(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# 1. Integrity has to cover every byte the harness will read.
# ---------------------------------------------------------------------------

class EveryByteReadIsHashed(_Tmp):
    """The integrity walk used `bundle_dir.iterdir()`, so it hashed only the
    top level of a bundle. Evidence in a subdirectory could be rewritten while
    the bundle hash, the integrity verdict and the run id all stayed
    identical — the exact tamper the tool exists to make impossible."""

    def _nested_bundle(self) -> Path:
        bundle_dir = self.root / "nested"
        (bundle_dir / "evidence").mkdir(parents=True)
        (bundle_dir / "evidence" / "items.jsonl").write_text(
            json.dumps(answer_item("a1", "The fee is 25 dollars.")) + "\n",
            encoding="utf-8")
        (bundle_dir / "evidence" / "responses.jsonl").write_text(
            json.dumps(response("a1", "The fee is 25 dollars.")) + "\n",
            encoding="utf-8")
        (bundle_dir / "manifest.json").write_text(json.dumps({
            "format": "plumbline-bundle", "format_version": 1,
            "name": "nested", "version": "1", "synthetic": True,
            "files": {"items": "evidence/items.jsonl",
                      "responses": "evidence/responses.jsonl"},
        }), encoding="utf-8")
        seal(bundle_dir)
        return bundle_dir

    def test_a_file_in_a_subdirectory_is_in_the_manifest(self):
        bundle_dir = self._nested_bundle()
        recorded = json.loads(
            (bundle_dir / "checksums.json").read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(recorded["files"]),
            ["evidence/items.jsonl", "evidence/responses.jsonl",
             "manifest.json"],
            "a nested file that is not in the manifest is not protected")

    def test_editing_evidence_in_a_subdirectory_is_refused(self):
        bundle_dir = self._nested_bundle()
        before = verify_integrity(bundle_dir)
        target = bundle_dir / "evidence" / "responses.jsonl"
        target.write_text(
            json.dumps(response("a1", "The fee is 900 dollars.")) + "\n",
            encoding="utf-8")
        with self.assertRaises(IntegrityError) as caught:
            verify_integrity(bundle_dir)
        self.assertIn("evidence/responses.jsonl", str(caught.exception))
        # And re-sealing moves the hash, so the edit leaves a trace either way.
        self.assertNotEqual(before, seal(bundle_dir)["bundle_sha256"])

    def test_a_symlink_anywhere_in_the_bundle_is_refused(self):
        bundle_dir = write_bundle(self.root, _items(), _responses())
        outside = self.root / "elsewhere.jsonl"
        outside.write_text("{}\n", encoding="utf-8")
        (bundle_dir / "linked.jsonl").symlink_to(outside)
        for call in (lambda: verify_integrity(bundle_dir),
                     lambda: seal(bundle_dir),
                     lambda: load(bundle_dir)):
            with self.assertRaises(IntegrityError) as caught:
                call()
            self.assertIn("symbolic link", str(caught.exception))

    def test_a_symlinked_subdirectory_is_refused(self):
        bundle_dir = write_bundle(self.root, _items(), _responses())
        target = self.root / "outside_dir"
        target.mkdir()
        (target / "planted.jsonl").write_text("{}\n", encoding="utf-8")
        (bundle_dir / "sub").symlink_to(target, target_is_directory=True)
        with self.assertRaises(IntegrityError):
            verify_integrity(bundle_dir)


class NothingUnsealedIsEverRead(_Tmp):
    """Verification proves the bundle's own inventory is intact. It says
    nothing about a path the manifest points at from outside that inventory,
    and `bundle_dir / filename` happily resolved `..` and absolute paths."""

    def _bundle_declaring(self, items_value: str) -> Path:
        bundle_dir = self.root / "b"
        bundle_dir.mkdir()
        (self.root / "outside.jsonl").write_text(
            json.dumps(answer_item("a1", "planted")) + "\n", encoding="utf-8")
        (bundle_dir / "responses.jsonl").write_text(
            json.dumps(response("a1", "planted")) + "\n", encoding="utf-8")
        (bundle_dir / "manifest.json").write_text(json.dumps({
            "format": "plumbline-bundle", "format_version": 1,
            "name": "b", "version": "1", "synthetic": True,
            "files": {"items": items_value, "responses": "responses.jsonl"},
        }), encoding="utf-8")
        seal(bundle_dir)
        return bundle_dir

    def test_a_parent_directory_escape_is_refused(self):
        bundle_dir = self._bundle_declaring("../outside.jsonl")
        with self.assertRaises(BundleError) as caught:
            load(bundle_dir)
        self.assertIn("outside the bundle", str(caught.exception))

    def test_an_absolute_path_is_refused(self):
        bundle_dir = self._bundle_declaring(
            str(self.root / "outside.jsonl"))
        with self.assertRaises(BundleError) as caught:
            load(bundle_dir)
        self.assertIn("absolute path", str(caught.exception))

    def test_a_declared_file_no_checksum_covers_is_refused(self):
        bundle_dir = write_bundle(self.root, _items(), _responses())
        # Drop one file from coverage, keeping the manifest self-consistent —
        # the shape a hand-edited checksums.json would take.
        checksums = bundle_dir / "checksums.json"
        recorded = json.loads(checksums.read_text(encoding="utf-8"))
        recorded["files"].pop("responses.jsonl")
        recorded["bundle_sha256"] = bundle_digest(recorded["files"])
        checksums.write_text(json.dumps(recorded), encoding="utf-8")
        with self.assertRaises(IntegrityError) as caught:
            load(bundle_dir)
        self.assertIn("present but not listed", str(caught.exception))

    def test_the_interface_snapshot_cannot_escape_either(self):
        bundle_dir = write_bundle(self.root, _items(), _responses(),
                                  interface="<html></html>")
        (self.root / "outside.html").write_text("<html></html>",
                                                encoding="utf-8")
        manifest_path = bundle_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["interface"] = "../outside.html"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        seal(bundle_dir)
        bundle = load(bundle_dir)
        with self.assertRaises(BundleError):
            get_suite("accessibility").evaluate(bundle, LexicalJudge(), 1.0)


class TheBundleHashIsUnambiguous(_Tmp):
    """`bundle_digest` joins `"<name>=<hex>\\n"` lines, so a file whose name
    contains a newline could serialize exactly like two ordinary files. POSIX
    allows such names, so the digest stays injective only because they are
    refused."""

    def test_a_newline_in_a_name_would_collide(self):
        forged = {"x=" + "a" * 64 + "\ny": "b" * 64}
        ordinary = {"x": "a" * 64, "y": "b" * 64}
        self.assertEqual(bundle_digest(forged), bundle_digest(ordinary),
                         "the collision this refusal exists to prevent")

    def test_such_a_name_is_refused(self):
        for name in ("x=" + "a" * 64 + "\ny", "a\rb", "a\x00b"):
            with self.assertRaises(IntegrityError):
                bundle_mod.check_hashable_name(name)

    def test_a_manifest_digest_that_is_not_a_digest_is_refused(self):
        bundle_dir = write_bundle(self.root, _items(), _responses())
        checksums = bundle_dir / "checksums.json"
        recorded = json.loads(checksums.read_text(encoding="utf-8"))
        recorded["files"]["manifest.json"] = "not-a-digest"
        recorded["bundle_sha256"] = bundle_digest(recorded["files"])
        checksums.write_text(json.dumps(recorded), encoding="utf-8")
        with self.assertRaises(IntegrityError) as caught:
            verify_integrity(bundle_dir)
        self.assertIn("sha256 hex digest", str(caught.exception))


class AMalformedManifestIsRefusedNotTrusted(_Tmp):
    """`checksums.json` is untrusted input: it is the one file in a bundle
    whose contents are not vouched for by anything. Every branch that rejects
    a malformed one is exercised here, because an unexercised refusal path is
    a refusal nobody has watched work."""

    def setUp(self):
        super().setUp()
        self.bundle_dir = write_bundle(self.root, _items(), _responses())
        self.checksums = self.bundle_dir / "checksums.json"

    def _rewrite(self, recorded):
        self.checksums.write_text(json.dumps(recorded), encoding="utf-8")

    def _recorded(self):
        return json.loads(self.checksums.read_text(encoding="utf-8"))

    def _refuses(self, fragment):
        with self.assertRaises(IntegrityError) as caught:
            verify_integrity(self.bundle_dir)
        self.assertIn(fragment, str(caught.exception))

    def test_a_manifest_that_is_not_an_object(self):
        self._rewrite(["not", "an", "object"])
        self._refuses("not a JSON object")

    def test_a_manifest_that_is_not_json_at_all(self):
        self.checksums.write_text("{ this is not json", encoding="utf-8")
        self._refuses("unreadable")

    def test_a_manifest_with_no_files_object(self):
        recorded = self._recorded()
        recorded.pop("files")
        self._rewrite(recorded)
        self._refuses("vouches for nothing")

    def test_a_manifest_whose_files_is_not_an_object(self):
        recorded = self._recorded()
        recorded["files"] = ["items.jsonl"]
        self._rewrite(recorded)
        self._refuses("vouches for nothing")

    def test_an_empty_file_name(self):
        recorded = self._recorded()
        recorded["files"][""] = "a" * 64
        self._rewrite(recorded)
        self._refuses("non-empty string")

    def test_a_bundle_hash_that_is_not_a_digest(self):
        recorded = self._recorded()
        recorded["bundle_sha256"] = "nope"
        self._rewrite(recorded)
        self._refuses("bundle_sha256 is not a lowercase sha256")

    def test_a_bundle_hash_that_does_not_match_the_per_file_digests(self):
        recorded = self._recorded()
        recorded["bundle_sha256"] = "0" * 64
        self._rewrite(recorded)
        self._refuses("does not match the per-file digests")

    def test_a_file_listed_but_absent(self):
        recorded = self._recorded()
        recorded["files"]["ghost.jsonl"] = "a" * 64
        recorded["bundle_sha256"] = bundle_digest(recorded["files"])
        self._rewrite(recorded)
        self._refuses("listed but missing: ghost.jsonl")

    def test_something_that_is_not_a_regular_file(self):
        import os
        try:
            os.mkfifo(self.bundle_dir / "pipe")
        except (AttributeError, NotImplementedError, OSError):
            self.skipTest("this platform has no FIFOs")
        self._refuses("not a regular file")

    def test_sealing_something_that_is_not_a_directory(self):
        with self.assertRaises(BundleError) as caught:
            seal(self.bundle_dir / "manifest.json")
        self.assertIn("not a directory", str(caught.exception))


# ---------------------------------------------------------------------------
# 2. Silence is never evidence.
# ---------------------------------------------------------------------------

class SilenceIsNotAPass(_Tmp):
    """A target that returned nothing at all used to score a perfect 1.00 on
    six suites and pass a gate outright, because every check phrased as an
    absence is satisfied by an absent response."""

    @classmethod
    def setUpClass(cls):
        cls._shared = tempfile.TemporaryDirectory()
        cls.silent_bundle = Path(cls._shared.name) / "silent"
        shutil.copytree(DEMO_BUNDLE, cls.silent_bundle)
        responses = cls.silent_bundle / "responses.jsonl"
        blanked = []
        for line in responses.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            record["response"] = ""
            blanked.append(json.dumps(record, ensure_ascii=False))
        responses.write_text("\n".join(blanked) + "\n", encoding="utf-8")
        seal(cls.silent_bundle)

    @classmethod
    def tearDownClass(cls):
        cls._shared.cleanup()

    # The suites that screen a response for the absence of something, or
    # compare two responses. None of them may report a pass over silence.
    ABSENCE_SUITES = ("groundedness", "privacy", "representational_harms",
                      "fairness", "cross_language")
    # The suites that ask whether the target behaved correctly. Silence is a
    # wrong behavior, so these score it zero rather than excluding it.
    BEHAVIOR_SUITES = ("smoke", "refusal", "accuracy", "adversarial",
                       "multilingual", "citation_validity")

    def _evaluate(self, suite_id):
        bundle = load(self.silent_bundle)
        suite = get_suite(suite_id)
        return suite.evaluate(bundle, LexicalJudge(), suite.default_floor)

    def test_no_absence_suite_reports_a_pass_over_a_dead_target(self):
        from plumbline.suites import EmptyPopulationError
        for suite_id in self.ABSENCE_SUITES:
            with self.subTest(suite=suite_id):
                try:
                    result = self._evaluate(suite_id)
                except EmptyPopulationError:
                    continue  # refused outright: also fail-closed
                self.assertEqual(
                    result.verdict, FAIL,
                    f"{suite_id} passed a target that said nothing")

    def test_every_behavior_suite_scores_a_dead_target_zero(self):
        for suite_id in self.BEHAVIOR_SUITES:
            with self.subTest(suite=suite_id):
                result = self._evaluate(suite_id)
                self.assertEqual(result.score, 0.0, suite_id)
                self.assertEqual(result.verdict, FAIL, suite_id)

    def test_the_gate_refuses_a_dead_target_on_the_absence_suites_alone(self):
        config = self.write_config("dead.toml", f"""
[target]
name = "dead-target"
[dataset]
path = {json.dumps(str(self.silent_bundle))}
[suites.groundedness]
floor = 0.70
[suites.privacy]
floor = 1.0
[suites.representational_harms]
floor = 1.0
[suites.fairness]
floor = 0.85
""")
        code, out, err = run_cli("gate", "--config", str(config),
                                 "--out", str(self.root / "out"))
        self.assertNotEqual(code, EXIT_PASS,
                            f"a target with 174 empty responses passed:\n{out}")

    def test_partial_silence_is_reported_as_uncovered_not_absorbed(self):
        """Losing a fifth of the responses must shrink the population a suite
        claims to have checked, not quietly improve its score."""
        partial = self.root / "partial"
        shutil.copytree(DEMO_BUNDLE, partial)
        responses = partial / "responses.jsonl"
        rewritten = []
        for n, line in enumerate(responses.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            record = json.loads(line)
            if n % 5 == 0:
                record["response"] = ""
            rewritten.append(json.dumps(record, ensure_ascii=False))
        responses.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        seal(partial)

        bundle = load(partial)
        suite = get_suite("privacy")
        result = suite.evaluate(bundle, LexicalJudge(), 1.0)
        block = result.details["unverifiable"]
        self.assertGreater(block["count"], 0)
        self.assertEqual(block["scored"] + block["count"], block["eligible"])
        self.assertEqual(result.n, block["scored"],
                         "n must be what was scored, not what was eligible")
        self.assertIn("silent", block["reasons"])


class SilenceThatGetsPastStrip(SilenceIsNotAPass):
    """The fix above tested `response.strip()`, so it caught the empty string
    and nothing else.

    A target answering every one of the 174 items with `"."` — or an emoji, or
    a zero-width space, or a bare `[src-id]` — scored the identical perfect
    1.0000 on the identical five suites and the gate returned PASS, exit 0. A
    response now counts only if something in it survives normalization."""

    RESPONSES = {
        "a full stop": ".",
        "an ellipsis": "...",
        "an emoji": "🙂",
        "a zero-width space": "​",
        "a bare citation": "[src-rent-cap]",
    }

    @classmethod
    def setUpClass(cls):
        # Deliberately shadows the parent's silent bundle with "." responses,
        # so every assertion in the parent class runs again against them.
        cls._shared = tempfile.TemporaryDirectory()
        cls.silent_bundle = Path(cls._shared.name) / "punctuation"
        shutil.copytree(DEMO_BUNDLE, cls.silent_bundle)
        responses = cls.silent_bundle / "responses.jsonl"
        rewritten = []
        for line in responses.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            record["response"] = "..."
            rewritten.append(json.dumps(record, ensure_ascii=False))
        responses.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        seal(cls.silent_bundle)

    def test_none_of_these_counts_as_a_response(self):
        from plumbline.suites import readable
        for description, text in self.RESPONSES.items():
            with self.subTest(response=description):
                self.assertFalse(readable(text), description)
        self.assertTrue(readable("The cap is 850 dollars. [src-rent-cap]"))
        self.assertTrue(readable("850"))

    def test_smoke_is_not_satisfied_by_a_full_stop(self):
        # Every other suite points at `smoke` when it excludes an item, so if
        # `smoke` accepts a full stop the whole argument is circular.
        result = self._evaluate("smoke")
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.verdict, FAIL)
        self.assertEqual(len(result.details["unreadable_items"]), 174)


class NothingAssertedIsNotWellGrounded(_Tmp):
    """`support_score` returns 1.0 for a claim with no content tokens —
    nothing was asserted, so nothing is unsupported. Sound arithmetic, and it
    let a target answering `"the and of to"` score a perfect 1.0000 on
    `groundedness` and `citation_accuracy` while `readable()` was satisfied."""

    def _bundle(self, text):
        return load(write_bundle(
            self.root,
            [answer_item("a1", "The cap is 850 dollars.",
                         sources=["src-cap"])],
            [response("a1", text)],
            sources=[{"id": "src-cap", "text": "The monthly cap is 850 "
                                               "dollars."}],
            name=f"vacuous-{abs(hash(text))}"))

    def test_a_response_of_function_words_is_not_scored(self):
        from plumbline.suites import EmptyPopulationError
        with self.assertRaises(EmptyPopulationError):
            get_suite("groundedness").evaluate(
                self._bundle("the and of to"), LexicalJudge(), 0.7)

    def test_it_is_named_as_unverifiable_when_other_items_are_scored(self):
        bundle = load(write_bundle(
            self.root,
            [answer_item("a1", "The cap is 850 dollars.", sources=["src-cap"]),
             answer_item("a2", "The cap is 850 dollars.", sources=["src-cap"])],
            [response("a1", "The monthly cap is 850 dollars. [src-cap]"),
             response("a2", "the and of to")],
            sources=[{"id": "src-cap",
                      "text": "The monthly cap is 850 dollars."}],
            name="vacuous-mixed"))
        result = get_suite("groundedness").evaluate(bundle, LexicalJudge(), 0.7)
        block = result.details["unverifiable"]
        self.assertEqual(block["reasons"]["no_claim"], ["a2"])
        self.assertEqual(result.n, 1)

    def test_citing_a_passage_you_took_nothing_from_scores_zero(self):
        bundle = load(write_bundle(
            self.root,
            [answer_item("a1", "The cap is 850 dollars.", sources=["src-cap"])],
            [response("a1", "[src-cap]")],
            sources=[{"id": "src-cap",
                      "text": "The monthly cap is 850 dollars."}],
            name="citation-only"))
        for suite_id in ("citation_validity", "citation_accuracy"):
            with self.subTest(suite=suite_id):
                result = get_suite(suite_id).evaluate(
                    bundle, LexicalJudge(), 0.8)
                self.assertEqual(result.score, 0.0)


class SilenceNobodyCountsIsStillAPass(_Tmp):
    """Excluding an unreadable item instead of scoring it 1.0 is right, and on
    its own it opens the quieter version of the same hole.

    On the released harness, a target that returned nothing for 116 of the
    demo's 174 items passed a gate enabling `groundedness`, `privacy`,
    `representational_harms`, `fairness` and `cross_language` — exit 0, five
    green rows, each annotated `116 unverifiable`. Every suite excluded the
    silence and no suite counted it."""

    ABSENCE_ONLY = """
[suites.groundedness]
floor = 0.70
[suites.privacy]
floor = 1.0
[suites.representational_harms]
floor = 1.0
[suites.fairness]
floor = 0.85
[suites.cross_language]
floor = 1.0
"""

    def _partial(self) -> Path:
        partial = self.root / "partial"
        shutil.copytree(DEMO_BUNDLE, partial)
        responses = partial / "responses.jsonl"
        rewritten = []
        for n, line in enumerate(responses.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            record = json.loads(line)
            if n % 3:
                record["response"] = ""
            rewritten.append(json.dumps(record, ensure_ascii=False))
        responses.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        seal(partial)
        return partial

    def _config(self, bundle_dir: Path, extra: str = "") -> Path:
        return self.write_config("partial.toml", f"""
[target]
name = "two-thirds-quiet"
[dataset]
path = {json.dumps(str(bundle_dir))}
{self.ABSENCE_ONLY}{extra}
""")

    def test_a_run_whose_suites_all_excuse_silence_reports_no_verdict(self):
        code, out, err = run_cli("gate", "--config",
                                 str(self._config(self._partial())),
                                 "--out", str(self.root / "out"))
        self.assertEqual(code, EXIT_CONFIG_ERROR, out)
        self.assertIn("no enabled suite counts that against the target", err)

    def test_the_error_names_a_suite_that_would_count_it(self):
        _, _, err = run_cli("gate", "--config",
                            str(self._config(self._partial())),
                            "--out", str(self.root / "out"))
        self.assertIn("smoke", err)

    def test_with_such_a_suite_enabled_it_is_a_measured_failure(self):
        config = self._config(self._partial(),
                              "[suites.smoke]\nfloor = 1.0\n")
        code, out, _ = run_cli("gate", "--config", str(config),
                               "--out", str(self.root / "out"))
        self.assertEqual(code, EXIT_SUITE_FAILURE, out)
        self.assertIn("GATE: FAIL", out)

    def test_a_target_that_answered_everything_is_unaffected(self):
        # The refusal fires on unreadable responses and nothing else: a clean
        # run must not have to enable a suite it did not want.
        config = self.write_config("clean.toml", f"""
[target]
name = "clean"
[dataset]
path = {json.dumps(str(DEMO_BUNDLE))}
{self.ABSENCE_ONLY}
""")
        code, out, _ = run_cli("gate", "--config", str(config),
                               "--out", str(self.root / "out"))
        self.assertEqual(code, EXIT_PASS, out)

    def test_the_rule_reads_the_run_rather_than_a_list_of_suite_names(self):
        # Not "is smoke enabled" — "did anything score these items zero". A
        # suite added tomorrow that scores silence counts without being listed.
        bundle = load(self._partial())
        result = get_suite("privacy").evaluate(bundle, LexicalJudge(), 1.0)
        with self.assertRaises(CoverageError):
            from plumbline.audit import refuse_uncounted_silence
            refuse_uncounted_silence(bundle, [result])
        smoke = get_suite("smoke").evaluate(bundle, LexicalJudge(), 1.0)
        from plumbline.audit import refuse_uncounted_silence
        refuse_uncounted_silence(bundle, [result, smoke])  # no raise


class BlankReferencesAreNotPerfectMatches(_Tmp):
    """`answer_score` returned 1.0 when both sides normalized away, so a
    reference answer of "   " against a response of "" was a perfect match."""

    def test_empty_against_empty_scores_zero(self):
        judge = LexicalJudge()
        self.assertEqual(judge.answer_score("", ""), 0.0)
        self.assertEqual(judge.answer_score("   ", "   "), 0.0)
        self.assertEqual(judge.answer_score("...", ""), 0.0)

    def test_a_whitespace_reference_answer_is_a_bundle_error(self):
        bundle_dir = write_bundle(self.root,
                                  [answer_item("a1", "   ")],
                                  [response("a1", "   ")])
        with self.assertRaises(BundleError) as caught:
            load(bundle_dir)
        self.assertIn("no expected answer", str(caught.exception))


# ---------------------------------------------------------------------------
# 3. No vacuous configuration.
# ---------------------------------------------------------------------------

class AFloorOfZeroIsNotACheck(_Tmp):
    """Every score in [0,1] clears a floor of zero, including a 0.0 from a
    suite that measured nothing: a green row that cannot go red."""

    def test_a_zero_floor_is_a_configuration_error(self):
        bundle_dir = write_bundle(self.root, _items(), _responses())
        config = self.write_config("zero.toml", f"""
[target]
name = "zero"
[dataset]
path = {json.dumps(str(bundle_dir))}
[suites.accuracy]
floor = 0.0
""")
        with self.assertRaises(ConfigError) as caught:
            load_config(config)
        self.assertIn("every possible score clears", str(caught.exception))

    def test_the_cli_refuses_it_rather_than_passing(self):
        bundle_dir = write_bundle(self.root, _items(), _responses())
        config = self.write_config("zero2.toml", f"""
[target]
name = "zero"
[dataset]
path = {json.dumps(str(bundle_dir))}
[suites.accuracy]
floor = 0.0
""")
        code, _, _ = run_cli("audit", "--config", str(config),
                             "--out", str(self.root / "o"))
        self.assertEqual(code, EXIT_CONFIG_ERROR)


# ---------------------------------------------------------------------------
# 4. The overall verdict cannot be reached by a value nobody recognized.
# ---------------------------------------------------------------------------

class UnrecognizedVerdictsAreNotPasses(_Tmp):
    """Aggregation was `FAIL if any(v == FAIL) else PASS`, so a suite
    returning "SKIP" — or None, or a typo — landed on the PASS branch."""

    def _result(self, **overrides):
        base = dict(suite_id="smoke", score=1.0, floor=1.0, verdict=PASS, n=1)
        base.update(overrides)
        return SuiteResult(**base)

    def test_a_third_verdict_stops_the_run(self):
        for verdict in ("SKIP", "skip", "pass", "", None, "UNVERIFIABLE"):
            with self.subTest(verdict=verdict):
                with self.assertRaises(ResultError):
                    validate_result(self._result(verdict=verdict),
                                    suite_id="smoke", floor=1.0)

    def test_a_pass_below_the_floor_stops_the_run(self):
        with self.assertRaises(ResultError):
            validate_result(self._result(score=0.2, floor=0.9, verdict=PASS),
                            suite_id="smoke", floor=0.9)

    def test_a_pass_alongside_load_bearing_failures_stops_the_run(self):
        with self.assertRaises(ResultError):
            validate_result(
                self._result(hard_failures=["a1"]), suite_id="smoke", floor=1.0)

    def test_a_score_outside_the_unit_interval_stops_the_run(self):
        for score in (-0.1, 1.5, float("nan")):
            with self.subTest(score=score):
                with self.assertRaises(ResultError):
                    validate_result(self._result(score=score, floor=0.0),
                                    suite_id="smoke", floor=0.0)

    def test_a_result_labelled_for_another_suite_stops_the_run(self):
        with self.assertRaises(ResultError):
            validate_result(self._result(suite_id="refusal"),
                            suite_id="smoke", floor=1.0)

    def test_a_misbehaving_suite_exits_five_not_one(self):
        """Exit 1 means "scored, and something failed". A suite that returned
        an uninterpretable verdict scored nothing."""
        bundle_dir = write_bundle(self.root, _items(), _responses())
        config_path = self.write_config("m.toml", f"""
[target]
name = "misbehaving"
[dataset]
path = {json.dumps(str(bundle_dir))}
[suites.smoke]
floor = 1.0
""")
        smoke = get_suite("smoke").__class__
        original = smoke.evaluate

        def skipping(self_, bundle, judge, floor):
            result = original(self_, bundle, judge, floor)
            result.verdict = "SKIP"
            return result

        smoke.evaluate = skipping
        self.addCleanup(setattr, smoke, "evaluate", original)
        code, _, err = run_cli("audit", "--config", str(config_path),
                               "--out", str(self.root / "o"))
        self.assertEqual(code, EXIT_INTERNAL_ERROR, err)


# ---------------------------------------------------------------------------
# 5. Exit codes distinguish a measurement from the absence of one.
# ---------------------------------------------------------------------------

class ACrashIsNotAMeasuredFailure(_Tmp):
    """An unhandled exception left the interpreter, which exits 1 — the code
    reserved for "scoring completed and a suite failed"."""

    def test_an_unexpected_error_exits_five(self):
        bundle_dir = write_bundle(self.root, _items(), _responses())
        config = self.write_config("c.toml", f"""
[target]
name = "crash"
[dataset]
path = {json.dumps(str(bundle_dir))}
[suites.smoke]
floor = 1.0
""")
        unwritable = self.root / "readonly"
        unwritable.mkdir(mode=0o500)
        self.addCleanup(unwritable.chmod, 0o700)
        code, _, err = run_cli("audit", "--config", str(config),
                               "--out", str(unwritable / "audits"))
        self.assertEqual(code, EXIT_INTERNAL_ERROR)
        self.assertNotEqual(code, EXIT_SUITE_FAILURE)
        self.assertIn("INTERNAL ERROR", err)

    def test_the_documented_codes_are_all_distinct(self):
        codes = [EXIT_PASS, EXIT_SUITE_FAILURE, EXIT_INTEGRITY_REFUSAL,
                 EXIT_CONFIG_ERROR, EXIT_INTERNAL_ERROR]
        self.assertEqual(len(set(codes)), len(codes))
        self.assertNotIn(0, codes[1:], "every non-zero code must block")


# ---------------------------------------------------------------------------
# 6. A run id names one run.
# ---------------------------------------------------------------------------

class RunIdsDoNotCollideAcrossTargets(_Tmp):
    """The run id is also the output directory. Two targets audited against
    the same evidence, judge and floors produced the same id, so the second
    run silently overwrote the first."""

    def test_the_target_is_part_of_run_identity(self):
        common = dict(harness_version="0", seed=1, dataset_sha256="d",
                      judge_config_sha256="j", suite_floors={"smoke": 1.0})
        self.assertNotEqual(compute_run_id(target="alpha", **common),
                            compute_run_id(target="bravo", **common))

    def test_two_targets_write_two_reports(self):
        bundle_dir = write_bundle(self.root, _items(), _responses())
        out = self.root / "shared"
        for name in ("county-alpha", "county-bravo"):
            config = self.write_config(f"{name}.toml", f"""
[target]
name = "{name}"
[dataset]
path = {json.dumps(str(bundle_dir))}
[suites.smoke]
floor = 1.0
""")
            code, _, err = run_cli("audit", "--config", str(config),
                                   "--out", str(out))
            self.assertEqual(code, EXIT_PASS, err)
        reports = sorted(out.glob("*/report.json"))
        self.assertEqual(len(reports), 2,
                         "one target's verdict overwrote the other's")
        targets = {json.loads(p.read_text(encoding="utf-8"))["target"]
                   for p in reports}
        self.assertEqual(targets, {"county-alpha", "county-bravo"})


# ---------------------------------------------------------------------------
# 7. The provenance stamp covers the body it stamps.
# ---------------------------------------------------------------------------

class TheReportIsSealedAgainstItsOwnContents(_Tmp):
    """Provenance described a run's inputs and nothing tied it to the output,
    so a score, a verdict or a whole suite row could be edited while the run
    id, dataset hash and judge hash all stayed valid."""

    def _audit(self) -> Path:
        bundle_dir = write_bundle(
            self.root,
            [answer_item("a1", "The fee is 25 dollars.")],
            [response("a1", "Something else entirely.")])
        config = self.write_config("s.toml", f"""
[target]
name = "sealed"
[dataset]
path = {json.dumps(str(bundle_dir))}
[suites.accuracy]
floor = 0.75
""")
        out = self.root / "out"
        code, _, _ = run_cli("audit", "--config", str(config), "--out", str(out))
        self.assertEqual(code, EXIT_SUITE_FAILURE)
        return next(out.glob("*/report.json"))

    def test_a_written_report_carries_a_seal_that_verifies(self):
        path = self._audit()
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn(REPORT_SEAL_FIELD, report["provenance"])
        self.assertEqual(verify_report(report),
                         report["provenance"][REPORT_SEAL_FIELD])

    def test_the_seal_does_not_cover_itself(self):
        path = self._audit()
        report = json.loads(path.read_text(encoding="utf-8"))
        with_seal = report_digest(report)
        report["provenance"].pop(REPORT_SEAL_FIELD)
        self.assertEqual(with_seal, report_digest(report))

    def test_laundering_a_failure_into_a_pass_is_detected(self):
        path = self._audit()
        report = json.loads(path.read_text(encoding="utf-8"))
        report["verdict"] = PASS
        report["suites"][0]["verdict"] = PASS
        report["suites"][0]["score"] = 0.99
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        with self.assertRaises(ReportSealError):
            verify_report(json.loads(path.read_text(encoding="utf-8")))
        code, _, err = run_cli("verify", str(path))
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL, err)

    def test_a_baseline_cannot_be_cut_from_an_edited_report(self):
        path = self._audit()
        report = json.loads(path.read_text(encoding="utf-8"))
        report["suites"][0]["score"] = 0.99
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        code, _, _ = run_cli("baseline", "--from", str(path),
                             "--out", str(self.root / "b.json"))
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
        self.assertFalse((self.root / "b.json").exists())

    def test_an_unsealed_report_is_refused_rather_than_trusted(self):
        path = self._audit()
        report = json.loads(path.read_text(encoding="utf-8"))
        report["provenance"].pop(REPORT_SEAL_FIELD)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        code, _, _ = run_cli("verify", str(path))
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)

    def test_verify_says_it_is_evidence_of_tampering_not_of_authorship(self):
        # The seal is a plain digest with no secret in it. A reader who takes
        # "seal matches" for "this came from the harness" has been misled by
        # this command, so the command says the boundary out loud.
        path = self._audit()
        _, out, _ = run_cli("verify", str(path))
        self.assertIn("tamper evidence, not authentication", out)


# ---------------------------------------------------------------------------
# 8. A run id has to be one the report's own contents generate.
# ---------------------------------------------------------------------------

class ARunIdIsDerivedNotDeclared(_Tmp):
    """The seal proves a report has not moved since it was written. It cannot
    prove which run wrote it: anyone who can edit the body can recompute a
    plain sha256 over the edit. So a report could be edited, re-sealed, and
    still present the run id of an earlier, trusted run — the id that names its
    output directory and that `plumbline baseline` copies into the committed
    bar as `source_run_id`. `verify` now recomputes the id from the inputs the
    report itself carries."""

    def _audit(self, name="derived", floor=0.75) -> Path:
        bundle_dir = write_bundle(
            self.root,
            [answer_item("a1", "The fee is 25 dollars.")],
            [response("a1", "The fee is 25 dollars.")],
            name=f"bundle-{name}")
        config = self.write_config(f"{name}.toml", f"""
[target]
name = "{name}"
[dataset]
path = {json.dumps(str(bundle_dir))}
[suites.accuracy]
floor = {floor}
""")
        out = self.root / f"out-{name}"
        code, _, err = run_cli("audit", "--config", str(config), "--out", str(out))
        self.assertEqual(code, EXIT_PASS, err)
        return next(out.glob("*/report.json"))

    @staticmethod
    def _reseal(path: Path, report: dict) -> None:
        """Write a report back the way a careful forger would: seal recomputed
        over the edit, so nothing but the derivation catches it."""
        from plumbline.report import seal_report
        report["provenance"].pop(REPORT_SEAL_FIELD, None)
        seal_report(report)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def test_an_honest_report_verifies(self):
        path = self._audit()
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(run_id_of(report), report["provenance"]["run_id"])
        code, out, err = run_cli("verify", str(path))
        self.assertEqual(code, EXIT_PASS, err)
        self.assertIn("derived from this report's own inputs", out)

    def test_a_borrowed_run_id_is_refused_even_though_the_seal_matches(self):
        path = self._audit()
        report = json.loads(path.read_text(encoding="utf-8"))
        report["target"] = "some-other-system"
        self._reseal(path, report)

        # The seal is genuinely valid: that is the point of the test.
        verify_report(json.loads(path.read_text(encoding="utf-8")))
        code, _, err = run_cli("verify", str(path))
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL, err)
        self.assertIn("generate", err)

    def test_a_lowered_floor_cannot_be_backdated_into_a_finished_report(self):
        path = self._audit()
        report = json.loads(path.read_text(encoding="utf-8"))
        report["suites"][0]["floor"] = 0.10
        self._reseal(path, report)
        code, _, _ = run_cli("verify", str(path))
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)

    def test_a_baseline_cannot_be_cut_from_a_report_with_a_borrowed_id(self):
        path = self._audit()
        report = json.loads(path.read_text(encoding="utf-8"))
        report["provenance"]["run_id"] = "0" * 16
        self._reseal(path, report)
        code, _, _ = run_cli("baseline", "--from", str(path),
                             "--out", str(self.root / "b.json"))
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
        self.assertFalse((self.root / "b.json").exists())

    def test_the_repositorys_own_committed_report_is_derivable(self):
        report = json.loads(
            next((REPO / "audits").glob("*/report.json")).read_text(
                encoding="utf-8"))
        self.assertEqual(run_id_of(report), report["provenance"]["run_id"])


if __name__ == "__main__":
    unittest.main()
