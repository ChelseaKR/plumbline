"""The optional model judge.

The properties under test are the ones that make it safe to offer at all: it
is never the default, it never runs inside the gate, a missing judgment is an
error rather than a zero, and a report it produced says so on its face.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import (
    LocalJSONServer,
    answer_item,
    refuse_item,
    response as recorded,
    run_cli,
    unused_url,
    write_bundle,
)
from plumbline.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_SUITE_FAILURE
from plumbline.judges import LexicalJudge, make_judge
from plumbline.model_judge import ModelJudgeError, _parse_score

ITEMS = [
    answer_item("m-001", "the monthly cap is 850 dollars"),
    answer_item("m-002", "applications close on the 15th"),
    refuse_item("m-003"),
]
RESPONSES = [
    recorded("m-001", "the cap each month is 850 dollars [src-cap]"),
    recorded("m-002", "you must apply by the 15th"),
    recorded("m-003", "I cannot help with that request"),
]

CONFIG_TEMPLATE = """\
[target]
name = "model-judge-test"

[dataset]
path = "{dataset_path}"

[judge]
kind = "model"
model = "test-grader-1"
mode = "{mode}"
cache = "{cache}"
endpoint = "{endpoint}"
timeout_seconds = 5
response_pointer = "score"

[judge.body]
reference = "{{expected}}"
answer = "{{actual}}"

[suites.smoke]
enabled = true
floor = 1.0

[suites.accuracy]
enabled = true
floor = 0.75
"""


LEXICAL_CONFIG_TEMPLATE = """\
[target]
name = "model-judge-test"

[dataset]
path = "{dataset_path}"

[judge]
kind = "lexical"

[suites.smoke]
enabled = true
floor = 1.0

[suites.accuracy]
enabled = true
floor = 0.75
"""


def judge_config(endpoint: str, cache: str | None = None, **overrides) -> dict:
    cfg = {
        "kind": "model",
        "model": "test-grader-1",
        "endpoint": endpoint,
        "response_pointer": "score",
        "timeout_seconds": 5,
        "body": {"reference": "{expected}", "answer": "{actual}"},
    }
    if cache is not None:
        cfg["cache"] = cache
    cfg.update(overrides)
    return cfg


def scoring(value):
    return lambda request: (200, {"score": value})


class TheDefaultIsLexical(unittest.TestCase):
    def test_no_judge_table_means_lexical(self):
        judge, warnings = make_judge({})
        self.assertIsInstance(judge, LexicalJudge)
        self.assertEqual(warnings, [])
        self.assertTrue(judge.describe()["deterministic"])

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            make_judge({"kind": "vibes"})
        self.assertIn("lexical, model", str(ctx.exception))

    def test_lexical_refuses_keys_meant_for_the_model_judge(self):
        with self.assertRaises(ValueError) as ctx:
            make_judge({"kind": "lexical", "model": "test-grader-1"})
        self.assertIn("kind = \"model\"", str(ctx.exception))


class ScoreParsing(unittest.TestCase):
    def test_accepts_a_number_or_a_numeric_string(self):
        self.assertEqual(_parse_score(0.5, where="t"), 0.5)
        self.assertEqual(_parse_score("0.25", where="t"), 0.25)

    def test_accepts_structured_output(self):
        self.assertEqual(_parse_score('{"score": 0.9}', where="t"), 0.9)

    def test_out_of_range_is_refused_not_clipped(self):
        for value in (4.2, -0.1, '{"score": 2}'):
            with self.subTest(value=value):
                with self.assertRaises(ModelJudgeError) as ctx:
                    _parse_score(value, where="t")
                self.assertIn("outside", str(ctx.exception))

    def test_prose_is_refused(self):
        with self.assertRaises(ModelJudgeError) as ctx:
            _parse_score("I would say it's pretty good", where="t")
        self.assertIn("not a score", str(ctx.exception))

    def test_booleans_and_objects_are_refused(self):
        for value in (True, {"nope": 1}, None):
            with self.subTest(value=value):
                with self.assertRaises(ModelJudgeError):
                    _parse_score(value, where="t")


class Configuration(unittest.TestCase):
    def build(self, cache=None, **overrides):
        overrides.setdefault("mode", "live")
        return make_judge(judge_config("http://127.0.0.1:9/x", cache=cache,
                                       **overrides))

    def test_a_valid_live_configuration_builds(self):
        judge, warnings = self.build()
        self.assertEqual(judge.kind, "model")
        self.assertEqual(len(warnings), 1, "live with no cache should warn")
        self.assertIn("will not be recorded", warnings[0])

    def test_live_with_a_cache_does_not_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, warnings = self.build(cache=str(Path(tmp) / "j.json"))
        self.assertEqual(warnings, [])

    def test_model_is_required(self):
        cfg = judge_config("http://127.0.0.1:9/x", mode="live")
        del cfg["model"]
        with self.assertRaises(ModelJudgeError) as ctx:
            make_judge(cfg)
        self.assertIn("[judge].model", str(ctx.exception))

    def test_cached_mode_requires_a_cache(self):
        with self.assertRaises(ModelJudgeError) as ctx:
            make_judge(judge_config("http://127.0.0.1:9/x", mode="cached"))
        self.assertIn("[judge].cache", str(ctx.exception))

    def test_body_must_use_both_texts(self):
        with self.assertRaises(ModelJudgeError) as ctx:
            self.build(body={"reference": "{expected}"})
        self.assertIn("{actual}", str(ctx.exception))

    def test_unknown_placeholder_is_refused(self):
        with self.assertRaises(ModelJudgeError):
            self.build(body={"a": "{expected}", "b": "{actual}", "c": "{prompt}"})

    def test_unknown_keys_are_refused(self):
        with self.assertRaises(ModelJudgeError) as ctx:
            self.build(temperature=0)
        self.assertIn("temperature", str(ctx.exception))

    def test_bad_mode_is_refused(self):
        with self.assertRaises(ModelJudgeError):
            self.build(mode="whatever")


class Judging(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cache = self.root / "judgments.json"

    def live(self, endpoint):
        judge, _ = make_judge(judge_config(endpoint, cache=str(self.cache),
                                           mode="live"))
        return judge

    def test_a_live_judgment_is_asked_for_and_recorded(self):
        with LocalJSONServer(scoring(0.8)) as server:
            judge = self.live(server.url)
            self.assertEqual(judge.answer_score("the cap is 850", "850 is the cap"), 0.8)
            self.assertEqual(len(server.requests), 1)
            self.assertEqual(server.requests[0]["body"],
                             {"reference": "the cap is 850", "answer": "850 is the cap"})
        recorded_cache = json.loads(self.cache.read_text())
        self.assertEqual(recorded_cache["format"], "plumbline-judgments")
        self.assertEqual(list(recorded_cache["judgments"].values()), [{"score": 0.8}])

    def test_a_recorded_judgment_is_replayed_without_a_call(self):
        with LocalJSONServer(scoring(0.8)) as server:
            self.live(server.url).answer_score("expected text", "actual text")
        # Same cache, an endpoint nothing is listening on, cached mode: if the
        # judge tried to call anything this would raise.
        judge, _ = make_judge(judge_config(unused_url(), cache=str(self.cache)))
        self.assertEqual(judge.answer_score("expected text", "actual text"), 0.8)

    def test_a_cache_miss_in_cached_mode_is_an_error_not_a_zero(self):
        judge, _ = make_judge(judge_config(unused_url(), cache=str(self.cache)))
        with self.assertRaises(ModelJudgeError) as ctx:
            judge.answer_score("never judged", "also never judged")
        self.assertIn("no recorded judgment", str(ctx.exception))

    def test_citation_markers_do_not_change_the_judgment(self):
        with LocalJSONServer(scoring(0.7)) as server:
            judge = self.live(server.url)
            judge.answer_score("the cap is 850", "the cap is 850 [src-cap]")
            judge.answer_score("the cap is 850", "the cap is 850")
            self.assertEqual(len(server.requests), 1,
                             "a source id is bookkeeping, not an answer")

    def test_an_unreachable_judge_is_a_named_failure(self):
        judge = self.live(unused_url())
        with self.assertRaises(ModelJudgeError) as ctx:
            judge.answer_score("a", "b")
        self.assertIn("could not reach", str(ctx.exception))

    def test_a_cache_from_a_different_judge_is_refused(self):
        with LocalJSONServer(scoring(0.8)) as server:
            self.live(server.url).answer_score("a", "b")
        with self.assertRaises(ModelJudgeError) as ctx:
            make_judge(judge_config(unused_url(), cache=str(self.cache),
                                    model="a-different-model"))
        self.assertIn("different judge", str(ctx.exception))

    def test_everything_but_answer_scoring_stays_lexical(self):
        judge, _ = make_judge(judge_config(unused_url(), cache=str(self.cache)))
        lexical = LexicalJudge()
        self.assertTrue(judge.is_refusal("I cannot help with that"))
        self.assertEqual(judge.support_score("the cap is 850", "the cap is 850"),
                         lexical.support_score("the cap is 850", "the cap is 850"))
        self.assertEqual(judge.config()["delegated_to_lexical"][0], "is_refusal")


class ConfigurationHash(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name) / "judgments.json"

    def test_a_model_judge_never_hashes_like_the_lexical_one(self):
        model, _ = make_judge(judge_config(unused_url(), cache=str(self.cache)))
        lexical, _ = make_judge({"kind": "lexical"})
        self.assertNotEqual(model.config_hash(), lexical.config_hash())

    def test_different_judgments_are_a_different_instrument(self):
        with LocalJSONServer(scoring(0.8)) as server:
            judge, _ = make_judge(judge_config(server.url, cache=str(self.cache),
                                               mode="live"))
            before = judge.config_hash()
            judge.answer_score("a", "b")
            after = judge.config_hash()
        self.assertNotEqual(before, after,
                            "the judgments themselves are part of the instrument")

    def test_no_secrets_or_paths_in_the_configuration(self):
        import os
        os.environ["PLUMBLINE_TEST_JUDGE_KEY"] = "sk-not-a-real-key"
        self.addCleanup(os.environ.pop, "PLUMBLINE_TEST_JUDGE_KEY", None)
        judge, _ = make_judge(judge_config(
            unused_url(), cache=str(self.cache),
            headers={"x-api-key": {"env": "PLUMBLINE_TEST_JUDGE_KEY"}}))
        rendered = json.dumps(judge.config())
        self.assertNotIn("sk-not-a-real-key", rendered)
        self.assertNotIn(str(self.cache), rendered)


class TheReportSaysSo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bundle = write_bundle(self.root, ITEMS, RESPONSES)
        self.cache = self.root / "judgments.json"

    def write_config(self, *, mode: str, endpoint: str) -> Path:
        path = self.root / f"target-{mode}.toml"
        path.write_text(CONFIG_TEMPLATE.format(
            dataset_path=self.bundle.as_posix(), mode=mode,
            cache=self.cache.as_posix(), endpoint=endpoint), encoding="utf-8")
        return path

    def record_judgments(self, score: float = 0.95) -> None:
        with LocalJSONServer(scoring(score)) as server:
            config = self.write_config(mode="live", endpoint=server.url)
            code, out, _ = run_cli("audit", "--config", config.as_posix(),
                                   "--out", (self.root / "live").as_posix())
        self.assertEqual(code, EXIT_PASS, out)

    def test_the_audit_report_leads_with_the_model_judge(self):
        self.record_judgments()
        config = self.write_config(mode="cached", endpoint=unused_url())
        code, out, err = run_cli("audit", "--config", config.as_posix(),
                                 "--out", (self.root / "audits").as_posix())
        self.assertEqual(code, EXIT_PASS, out)
        self.assertIn("NOT DETERMINISTIC", out)
        self.assertIn("model judge", err)  # warned, never suppressed

        report_dir = next((self.root / "audits").iterdir())
        report = json.loads((report_dir / "report.json").read_text())
        markdown = (report_dir / "report.md").read_text()
        self.assertEqual(report["judge"]["kind"], "model")
        self.assertFalse(report["judge"]["deterministic"])
        self.assertEqual(report["provenance"]["judge_kind"], "model")
        self.assertIn("**Scored by a model judge.**", markdown)
        self.assertIn("test-grader-1", markdown)
        self.assertIn("not deterministic", markdown)
        # The banner sits above everything but the verdict.
        self.assertLess(markdown.index("Scored by a model judge"),
                        markdown.index("## Provenance"))

    def test_a_lexical_baseline_cannot_be_compared_with_a_model_judged_run(self):
        lexical_config = self.root / "lexical.toml"
        lexical_config.write_text(
            LEXICAL_CONFIG_TEMPLATE.format(dataset_path=self.bundle.as_posix()),
            encoding="utf-8")
        # The lexical judge scores these paraphrases below the accuracy floor,
        # which is the whole motivation for offering a model judge. So this is
        # a FAIL baseline — and the point of the test is that the later
        # comparison still names the flip while refusing to subtract scores.
        code, out, _ = run_cli("audit", "--config", lexical_config.as_posix(),
                               "--out", (self.root / "lex").as_posix())
        self.assertEqual(code, EXIT_SUITE_FAILURE, out)
        lex_report = next((self.root / "lex").iterdir()) / "report.json"
        baseline = self.root / "baseline.json"
        run_cli("baseline", "--from", lex_report.as_posix(),
                "--out", baseline.as_posix())
        self.assertEqual(json.loads(baseline.read_text())["judge_kind"], "lexical")

        self.record_judgments()
        config = self.write_config(mode="cached", endpoint=unused_url())
        code, out, _ = run_cli("audit", "--config", config.as_posix(),
                               "--baseline", baseline.as_posix(),
                               "--out", (self.root / "audits2").as_posix())
        self.assertEqual(code, EXIT_PASS, out)
        self.assertIn("REFUSED", out)
        self.assertIn("judge configuration hash differs", out)
        # Categorical facts survive a refused numeric comparison.
        self.assertIn("flipped: accuracy FAIL -> PASS", out)


class TheGateStaysOffline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bundle = write_bundle(self.root, ITEMS, RESPONSES)
        self.cache = self.root / "judgments.json"

    def write_config(self, *, mode: str, endpoint: str) -> Path:
        path = self.root / f"gate-{mode}.toml"
        path.write_text(CONFIG_TEMPLATE.format(
            dataset_path=self.bundle.as_posix(), mode=mode,
            cache=self.cache.as_posix(), endpoint=endpoint), encoding="utf-8")
        return path

    def test_the_gate_refuses_a_live_model_judge(self):
        with LocalJSONServer(scoring(0.95)) as server:
            config = self.write_config(mode="live", endpoint=server.url)
            code, _, err = run_cli("gate", "--config", config.as_posix(),
                                   "--out", (self.root / "audits").as_posix())
            self.assertEqual(server.requests, [], "the gate must not call out")
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("not a gate", err)

    def test_the_gate_runs_a_cached_model_judge_without_a_socket(self):
        import socket

        with LocalJSONServer(scoring(0.95)) as server:
            live = self.write_config(mode="live", endpoint=server.url)
            run_cli("audit", "--config", live.as_posix(),
                    "--out", (self.root / "live").as_posix())
        config = self.write_config(mode="cached", endpoint=unused_url())

        def refuse(*args, **kwargs):
            raise AssertionError("the gate opened a socket")

        original = socket.socket
        socket.socket = refuse
        try:
            code, out, _ = run_cli("gate", "--config", config.as_posix(),
                                   "--out", (self.root / "audits").as_posix())
        finally:
            socket.socket = original
        self.assertEqual(code, EXIT_PASS, out)
        self.assertIn("NOT DETERMINISTIC", out)


if __name__ == "__main__":
    unittest.main()
