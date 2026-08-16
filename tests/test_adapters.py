"""Live-target adapters and the `record` command.

The adapter is exercised against a real HTTP server on the loopback
interface — a mocked opener would prove the code parses its own fixtures. The
last class in this file is the one that matters most: it asserts that none of
this can reach an audit.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import (
    LocalJSONServer,
    answer_item,
    refuse_item,
    run_cli,
    unused_url,
    write_bundle,
    write_question_set,
)
from plumbline import recording
from plumbline.adapters import AdapterError, available, make_adapter
from plumbline.bundle import Bundle, load as load_bundle, load_questions
from plumbline.cli import EXIT_CONFIG_ERROR, EXIT_INTEGRITY_REFUSAL, EXIT_PASS, EXIT_SUITE_FAILURE

ITEMS = [
    answer_item("q-001", "the cap is 850 dollars", load_bearing=True),
    answer_item("q-002", "applications close on the 15th"),
    refuse_item("q-003"),
]

CONFIG_TEMPLATE = """\
[target]
name = "record-test"

[dataset]
path = "{dataset_path}"

[judge]
kind = "lexical"

[adapter]
kind = "http_json"
endpoint = "{endpoint}"
response_pointer = "reply"
timeout_seconds = 5
{extra}

[adapter.body]
question = "{{prompt}}"
locale = "{{lang}}"

[suites.smoke]
enabled = true
floor = 1.0
"""


def adapter_config(endpoint: str, **overrides) -> dict:
    cfg = {
        "kind": "http_json",
        "endpoint": endpoint,
        "response_pointer": "reply",
        "timeout_seconds": 5,
        "body": {"question": "{prompt}", "locale": "{lang}"},
    }
    cfg.update(overrides)
    return cfg


def answering(text="the cap is 850 dollars"):
    return lambda request: (200, {"reply": text})


def echoing(request):
    """Answer with what was asked, so the test can see the request shape."""
    return 200, {"reply": f"you asked {request['body']['question']} "
                          f"in {request['body']['locale']}"}


class Registry(unittest.TestCase):
    def test_http_json_is_registered(self):
        self.assertIn("http_json", available())

    def test_no_adapter_table_is_an_error(self):
        with self.assertRaises(AdapterError) as ctx:
            make_adapter({})
        self.assertIn("[adapter]", str(ctx.exception))

    def test_unknown_kind_is_refused_not_defaulted(self):
        with self.assertRaises(AdapterError) as ctx:
            make_adapter({"kind": "carrier_pigeon"})
        self.assertIn("http_json", str(ctx.exception))


class HttpJsonConfiguration(unittest.TestCase):
    def build(self, **overrides):
        return make_adapter(adapter_config("http://127.0.0.1:9/x", **overrides))

    def test_a_valid_configuration_builds(self):
        adapter, warnings = self.build()
        self.assertEqual(adapter.kind, "http_json")
        self.assertEqual(warnings, [])

    def test_endpoint_is_validated(self):
        with self.assertRaises(AdapterError):
            make_adapter(adapter_config("file:///etc/passwd"))

    def test_body_is_required(self):
        cfg = adapter_config("http://127.0.0.1:9/x")
        del cfg["body"]
        with self.assertRaises(AdapterError) as ctx:
            make_adapter(cfg)
        self.assertIn("[adapter.body]", str(ctx.exception))

    def test_body_must_use_the_prompt(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(body={"question": "hello"})
        self.assertIn("{prompt}", str(ctx.exception))

    def test_unknown_placeholders_are_refused(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(body={"question": "{prompt}", "who": "{user_name}"})
        self.assertIn("user_name", str(ctx.exception))

    def test_response_pointer_is_required(self):
        cfg = adapter_config("http://127.0.0.1:9/x")
        del cfg["response_pointer"]
        with self.assertRaises(AdapterError):
            make_adapter(cfg)

    def test_unknown_keys_are_refused_rather_than_ignored(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(timout_seconds=5)
        self.assertIn("timout_seconds", str(ctx.exception))

    def test_bounds_are_validated(self):
        for override in ({"timeout_seconds": 0}, {"retries": 99},
                         {"min_interval_seconds": -1}, {"max_items": 0},
                         {"on_error": "shrug"}, {"method": "GET"}):
            with self.subTest(override=override):
                with self.assertRaises(AdapterError):
                    self.build(**override)

    def test_describe_records_the_shape_and_no_secrets(self):
        adapter, warnings = self.build(headers={"Authorization": "Bearer hunter2"})
        described = json.dumps(adapter.describe())
        self.assertNotIn("hunter2", described)
        self.assertIn("Authorization", described)
        self.assertEqual(len(adapter.describe()["request_sha256"]), 64)
        self.assertEqual(len(warnings), 1, "a literal secret should warn")


class HttpJsonCalls(unittest.TestCase):
    def test_the_prompt_reaches_the_target_and_the_answer_comes_back(self):
        with LocalJSONServer(echoing) as server:
            adapter, _ = make_adapter(adapter_config(server.url + "/chat"))
            answer = adapter.respond(ITEMS_AS_OBJECTS[0])
        self.assertEqual(answer, "you asked prompt for q-001 in en")
        self.assertEqual(server.requests[0]["path"], "/chat")

    def test_a_non_string_answer_is_refused(self):
        with LocalJSONServer(lambda r: (200, {"reply": {"text": "hi"}})) as server:
            adapter, _ = make_adapter(adapter_config(server.url))
            with self.assertRaises(AdapterError) as ctx:
                adapter.respond(ITEMS_AS_OBJECTS[0])
        self.assertIn("q-001", str(ctx.exception))

    def test_an_unreachable_target_names_the_item(self):
        adapter, _ = make_adapter(adapter_config(unused_url()))
        with self.assertRaises(AdapterError) as ctx:
            adapter.respond(ITEMS_AS_OBJECTS[0])
        self.assertIn("q-001", str(ctx.exception))

    def test_the_throttle_waits_between_calls(self):
        slept: list[float] = []
        ticks = iter([0.0, 0.0, 0.1, 0.6])
        with LocalJSONServer(answering()) as server:
            adapter, _ = make_adapter(
                adapter_config(server.url, min_interval_seconds=0.5))
            adapter._sleep = slept.append
            adapter._clock = lambda: next(ticks)
            adapter.respond(ITEMS_AS_OBJECTS[0])
            adapter.respond(ITEMS_AS_OBJECTS[1])
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], 0.4, places=6)


class Recording(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.questions = write_question_set(self.root, ITEMS)

    def record_with(self, server_handler, **overrides):
        with LocalJSONServer(server_handler) as server:
            adapter, _ = make_adapter(adapter_config(server.url, **overrides))
            return recording.record(
                questions=load_questions(self.questions), adapter=adapter,
                out_dir=self.root / "recorded", **{})

    def test_a_recording_is_an_ordinary_sealed_bundle(self):
        result = self.record_with(answering("the cap is 850 dollars"))
        self.assertEqual(result.recorded, 3)
        bundle = load_bundle(result.out_dir)  # verifies integrity
        self.assertEqual(len(bundle.responses), 3)
        self.assertEqual(bundle.responses["q-001"], "the cap is 850 dollars")

    def test_the_manifest_names_the_question_set_it_came_from(self):
        questions_hash = load_questions(self.questions).dataset_sha256
        result = self.record_with(answering())
        rec = result.manifest["recording"]
        self.assertEqual(rec["mode"], "live")
        self.assertEqual(rec["questions"]["sha256"], questions_hash)
        self.assertEqual(rec["adapter"]["kind"], "http_json")
        self.assertRegex(rec["recorded_at"], r"^\d{4}-\d{2}-\d{2}T[\d:]{8}\+00:00$")

    def test_a_recorded_bundle_is_not_synthetic_unless_declared(self):
        result = self.record_with(answering())
        self.assertFalse(result.manifest["synthetic"])
        self.assertIn("recorded from a live target",
                      result.manifest["description"])

    def test_recording_over_the_question_set_is_refused(self):
        with LocalJSONServer(answering()) as server:
            adapter, _ = make_adapter(adapter_config(server.url))
            with self.assertRaises(recording.RecordingError) as ctx:
                recording.record(questions=load_questions(self.questions),
                                 adapter=adapter, out_dir=self.questions)
        self.assertIn("refusing to record over", str(ctx.exception))

    def test_an_existing_recording_is_not_replaced_silently(self):
        self.record_with(answering("first"))
        with self.assertRaises(recording.RecordingError):
            self.record_with(answering("second"))
        with LocalJSONServer(answering("second")) as server:
            adapter, _ = make_adapter(adapter_config(server.url))
            result = recording.record(questions=load_questions(self.questions),
                                      adapter=adapter,
                                      out_dir=self.root / "recorded",
                                      overwrite=True)
        self.assertEqual(load_bundle(result.out_dir).responses["q-001"], "second")

    def test_a_failed_call_aborts_and_leaves_nothing_sealed(self):
        adapter, _ = make_adapter(adapter_config(unused_url()))
        with self.assertRaises(AdapterError):
            recording.record(questions=load_questions(self.questions),
                             adapter=adapter, out_dir=self.root / "aborted")
        self.assertFalse((self.root / "aborted" / "checksums.json").exists(),
                         "an aborted recording must not leave a gradable bundle")

    def test_record_empty_is_visible_and_fails_the_smoke_suite(self):
        state = {"calls": 0}

        def one_failure(request):
            state["calls"] += 1
            if state["calls"] == 2:
                return 500, {"error": "boom"}
            return 200, {"reply": "an answer"}

        result = self.record_with(one_failure, on_error="record_empty")
        self.assertEqual([e["id"] for e in result.empty], ["q-002"])
        self.assertEqual(
            result.manifest["recording"]["responses_recorded_empty"][0]["id"],
            "q-002")
        bundle = load_bundle(result.out_dir)
        self.assertEqual(bundle.responses["q-002"], "")

    def test_max_items_bounds_what_can_be_sent(self):
        with LocalJSONServer(answering()) as server:
            adapter, _ = make_adapter(adapter_config(server.url, max_items=2))
            with self.assertRaises(recording.RecordingError) as ctx:
                recording.record(questions=load_questions(self.questions),
                                 adapter=adapter, out_dir=self.root / "bounded")
            self.assertEqual(server.requests, [],
                             "the bound is checked before any request")
        self.assertIn("max_items", str(ctx.exception))

    def test_sources_and_interface_are_carried_across(self):
        questions = write_question_set(
            self.root, [answer_item("q-010", "yes", sources=["s-1"])],
            name="with-corpus",
            sources=[{"id": "s-1", "text": "yes indeed"}],
            interface="<html lang='en'></html>")
        with LocalJSONServer(answering("yes indeed")) as server:
            adapter, _ = make_adapter(adapter_config(server.url))
            result = recording.record(questions=load_questions(questions),
                                      adapter=adapter,
                                      out_dir=self.root / "corpus-recording")
        bundle = load_bundle(result.out_dir)
        self.assertIn("s-1", bundle.sources)
        self.assertTrue((result.out_dir / "interface.html").exists())


ITEMS_AS_OBJECTS: list = []


class RecordCommand(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.questions = write_question_set(self.root, ITEMS)

    def write_config(self, endpoint: str, extra: str = "") -> Path:
        path = self.root / "target.toml"
        path.write_text(CONFIG_TEMPLATE.format(
            dataset_path=self.questions.as_posix(), endpoint=endpoint,
            extra=extra), encoding="utf-8")
        return path

    def test_record_then_audit_is_the_whole_loop(self):
        with LocalJSONServer(answering("the cap is 850 dollars")) as server:
            config = self.write_config(server.url + "/chat")
            code, out, _ = run_cli("record", "--config", config.as_posix(),
                                   "--out", (self.root / "rec").as_posix())
        self.assertEqual(code, EXIT_PASS, out)
        self.assertIn("recorded:  3 responses", out)

        audit_config = self.root / "audit.toml"
        audit_config.write_text(CONFIG_TEMPLATE.format(
            dataset_path=(self.root / "rec").as_posix(),
            endpoint="http://127.0.0.1:9/unused", extra=""), encoding="utf-8")
        code, out, _ = run_cli("audit", "--config", audit_config.as_posix(),
                               "--out", (self.root / "audits").as_posix())
        self.assertEqual(code, EXIT_PASS, out)
        self.assertIn("verdict: PASS", out)

    def test_the_report_says_the_answers_were_recorded_live(self):
        with LocalJSONServer(answering("the cap is 850 dollars")) as server:
            config = self.write_config(server.url + "/chat")
            run_cli("record", "--config", config.as_posix(),
                    "--out", (self.root / "rec").as_posix())
        audit_config = self.root / "audit.toml"
        audit_config.write_text(CONFIG_TEMPLATE.format(
            dataset_path=(self.root / "rec").as_posix(),
            endpoint="http://127.0.0.1:9/unused", extra=""), encoding="utf-8")
        run_cli("audit", "--config", audit_config.as_posix(),
                "--out", (self.root / "audits").as_posix())
        report_dir = next((self.root / "audits").iterdir())
        report = json.loads((report_dir / "report.json").read_text())
        markdown = (report_dir / "report.md").read_text()
        self.assertEqual(report["dataset"]["recording"]["mode"], "live")
        self.assertIn("recorded from a live target**", markdown)
        self.assertIn("http_json", markdown)

    def test_a_tampered_question_set_is_refused_before_any_request(self):
        items = self.questions / "items.jsonl"
        items.write_text(items.read_text() + json.dumps(
            answer_item("q-999", "planted")) + "\n", encoding="utf-8")
        with LocalJSONServer(answering()) as server:
            config = self.write_config(server.url)
            code, _, err = run_cli("record", "--config", config.as_posix(),
                                   "--out", (self.root / "rec").as_posix())
            self.assertEqual(server.requests, [])
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
        self.assertIn("INTEGRITY REFUSAL", err)

    def test_an_unreachable_target_is_a_configuration_error_not_a_score(self):
        config = self.write_config(unused_url())
        code, _, err = run_cli("record", "--config", config.as_posix(),
                               "--out", (self.root / "rec").as_posix())
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("could not reach", err)

    def test_synthetic_must_be_declared(self):
        with LocalJSONServer(answering()) as server:
            config = self.write_config(server.url)
            run_cli("record", "--config", config.as_posix(), "--synthetic",
                    "--note", "recorded against the bundled fixture target",
                    "--out", (self.root / "rec").as_posix())
        manifest = json.loads((self.root / "rec" / "manifest.json").read_text())
        self.assertTrue(manifest["synthetic"])
        self.assertEqual(manifest["recording"]["note"],
                         "recorded against the bundled fixture target")

    def test_empty_responses_fail_the_gate_rather_than_passing_quietly(self):
        with LocalJSONServer(lambda r: (500, {"error": "down"})) as server:
            config = self.write_config(server.url, extra='on_error = "record_empty"')
            code, out, err = run_cli("record", "--config", config.as_posix(),
                                     "--out", (self.root / "rec").as_posix())
        self.assertEqual(code, EXIT_PASS, out)
        self.assertIn("empty:     3", out)
        self.assertIn("WARNING", err)

        audit_config = self.root / "audit.toml"
        audit_config.write_text(CONFIG_TEMPLATE.format(
            dataset_path=(self.root / "rec").as_posix(),
            endpoint="http://127.0.0.1:9/unused", extra=""), encoding="utf-8")
        code, out, _ = run_cli("gate", "--config", audit_config.as_posix(),
                               "--out", (self.root / "audits").as_posix())
        self.assertEqual(code, EXIT_SUITE_FAILURE)
        self.assertIn("smoke", out)


class TheGateStaysOffline(unittest.TestCase):
    """An adapter must never become a hidden network dependency of the gate."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bundle = write_bundle(
            self.root, ITEMS,
            [{"id": "q-001", "response": "the cap is 850 dollars"},
             {"id": "q-002", "response": "applications close on the 15th"},
             {"id": "q-003", "response": "I cannot help with that"}])

    def config_with_adapter(self) -> Path:
        path = self.root / "target.toml"
        path.write_text(CONFIG_TEMPLATE.format(
            dataset_path=self.bundle.as_posix(), endpoint=unused_url(),
            extra=""), encoding="utf-8")
        return path

    def test_an_audit_ignores_the_adapter_entirely(self):
        code, out, _ = run_cli("gate", "--config",
                               self.config_with_adapter().as_posix(),
                               "--out", (self.root / "audits").as_posix())
        self.assertEqual(code, EXIT_PASS, out)

    def test_an_audit_never_imports_the_adapter_package(self):
        script = (
            "import sys, json\n"
            "from plumbline.cli import main\n"
            f"code = main(['gate', '--config', {str(self.config_with_adapter())!r},"
            f" '--out', {str(self.root / 'audits2')!r}])\n"
            "loaded = sorted(m for m in sys.modules if m.startswith('plumbline'))\n"
            "print(json.dumps({'code': code, 'loaded': loaded}))\n"
        )
        src = Path(__file__).resolve().parent.parent / "src"
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True,
                              env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(result["code"], EXIT_PASS)
        for module in ("plumbline.adapters", "plumbline.adapters.http_json",
                       "plumbline.network", "plumbline.recording"):
            self.assertNotIn(module, result["loaded"])

    def test_scoring_does_not_open_a_socket(self):
        """Belt and braces: block the socket module and audit anyway."""
        import socket

        config = self.config_with_adapter()  # written before the block goes up

        def refuse(*args, **kwargs):
            raise AssertionError("the gate opened a socket")

        original = socket.socket
        socket.socket = refuse
        try:
            code, out, _ = run_cli("audit", "--config", config.as_posix(),
                                   "--out", (self.root / "audits3").as_posix())
        finally:
            socket.socket = original
        self.assertEqual(code, EXIT_PASS, out)


def setUpModule():
    """Item objects for the adapter-level tests, parsed the way the harness
    parses them."""
    with tempfile.TemporaryDirectory() as tmp:
        questions = write_question_set(Path(tmp), ITEMS)
        ITEMS_AS_OBJECTS.extend(load_questions(questions).items)


if __name__ == "__main__":
    unittest.main()


class ValidatingAQuestionSet(unittest.TestCase):
    """You should be able to inspect what you are about to send to a live
    target before you send it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_validate_accepts_a_bundle_with_no_responses(self):
        questions = write_question_set(self.root, ITEMS)
        code, out, _ = run_cli("validate", questions.as_posix())
        self.assertEqual(code, EXIT_PASS, out)
        self.assertIn("items:    3", out)
        self.assertIn("this is a question set", out)
        self.assertIn("integrity: OK", out)

    def test_validate_still_refuses_unverifiable_evidence(self):
        questions = write_question_set(self.root, ITEMS)
        (questions / "checksums.json").unlink()
        code, _, err = run_cli("validate", questions.as_posix())
        self.assertEqual(code, EXIT_INTEGRITY_REFUSAL)
        self.assertIn("INTEGRITY REFUSAL", err)

    def test_validate_names_a_recording_and_counts_responses(self):
        questions = write_question_set(self.root, ITEMS)
        with LocalJSONServer(answering("an answer")) as server:
            adapter, _ = make_adapter(adapter_config(server.url))
            result = recording.record(questions=load_questions(questions),
                                      adapter=adapter,
                                      out_dir=self.root / "recorded")
        code, out, _ = run_cli("validate", result.out_dir.as_posix())
        self.assertEqual(code, EXIT_PASS, out)
        self.assertIn("responses: 3, one per item", out)
        self.assertIn("via the http_json adapter", out)

    def test_recording_into_the_dataset_path_without_a_question_set_is_refused(self):
        """The likeliest first-time mistake: no [adapter].questions, so the
        recorder would be pointed at the bundle it is meant to produce."""
        bundle = write_bundle(self.root, ITEMS, [
            {"id": i["id"], "response": "x"} for i in ITEMS])
        config = self.root / "target.toml"
        with LocalJSONServer(answering()) as server:
            config.write_text(CONFIG_TEMPLATE.format(
                dataset_path=bundle.as_posix(), endpoint=server.url, extra=""),
                encoding="utf-8")
            code, _, err = run_cli("record", "--config", config.as_posix())
            self.assertEqual(server.requests, [])
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("refusing to record over the question set", err)
