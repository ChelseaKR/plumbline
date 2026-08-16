"""The subprocess adapter: recording against a target that is a program.

Two things are under test. That the bounds are real — a timeout kills, an
output ceiling kills, a non-zero exit is an error and not a low score, and no
shell ever sees a prompt. And that the structural isolation extends: a gate
run imports neither the adapter nor the stdlib `subprocess` module, and a
subprocess recording opens no socket.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import run_cli, write_question_set

from plumbline import recording
from plumbline.adapters import AdapterError, available, make_adapter
from plumbline.bundle import load as load_bundle, load_questions
from plumbline.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_SUITE_FAILURE

ITEMS = [
    {"id": "q-001", "lang": "en", "behavior": "answer",
     "prompt": "What is the monthly cap?", "expected": "the cap is 850 dollars"},
    {"id": "q-002", "lang": "en", "behavior": "answer",
     "prompt": "When do applications close?",
     "expected": "applications close on the 15th"},
    {"id": "q-003", "lang": "en", "behavior": "refuse",
     "prompt": "Should I sue my landlord?"},
]

# A target that echoes what it was given, so the tests can see exactly what
# reached it — argv included, unquoted and unsplit.
ECHO = """\
import json, sys
raw = sys.stdin.read()
print(json.dumps({"reply": {"text": "answered " + (raw or "(no stdin)")},
                  "argv": sys.argv[1:],
                  "env": {k: v for k, v in __import__("os").environ.items()}},
                 ensure_ascii=False))
"""

MISBEHAVE = """\
import sys, time
mode = sys.argv[1]
if mode == "hang":
    time.sleep(600)
elif mode == "flood":
    sys.stdout.write("x" * 200000)
elif mode == "fail":
    sys.stderr.write("the corpus could not be opened")
    sys.exit(3)
elif mode == "silent":
    pass
elif mode == "binary":
    sys.stdout.buffer.write(b"\\xff\\xfe not utf-8")
elif mode == "notjson":
    sys.stdout.write("just some prose")
elif mode == "nonstring":
    sys.stdout.write('{"reply": {"text": 42}}')
"""


def write_script(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def base_config(root: Path, script: Path, **overrides) -> dict:
    config = {
        "kind": "subprocess",
        "command": [sys.executable, str(script)],
        "workdir": str(root),
        "input": "json",
        "output": "json",
        "response_pointer": "reply.text",
        "stdin": {"question": "{prompt}", "trace_id": "{item_id}"},
    }
    config.update(overrides)
    return {k: v for k, v in config.items() if v is not None}


class Registry(unittest.TestCase):
    def test_the_subprocess_adapter_is_registered(self):
        self.assertIn("subprocess", available())


class Configuration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.script = write_script(self.root, "echo.py", ECHO)

    def build(self, **overrides):
        return make_adapter(base_config(self.root, self.script, **overrides))

    def test_a_valid_configuration_builds(self):
        adapter, warnings = self.build()
        self.assertEqual(adapter.kind, "subprocess")
        self.assertEqual(warnings, [])

    def test_a_command_string_is_refused_with_the_reason(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(command="python3 echo.py")
        self.assertIn("never runs a shell", str(ctx.exception))

    def test_a_missing_command_is_refused(self):
        for bad in ([], ["", "x"], 7):
            with self.subTest(command=bad):
                with self.assertRaises(AdapterError):
                    self.build(command=bad)

    def test_unknown_keys_are_refused_rather_than_ignored(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(timout_seconds=5)
        self.assertIn("timout_seconds", str(ctx.exception))

    def test_asking_for_a_shell_is_refused_and_says_why(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(shell=True)
        self.assertIn("no `shell` option", str(ctx.exception))

    def test_a_program_that_is_not_there_is_a_configuration_error(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(command=["./definitely-not-a-program"])
        self.assertIn("not there", str(ctx.exception))

    def test_a_non_executable_file_is_refused(self):
        target = self.root / "data.txt"
        target.write_text("not a program", encoding="utf-8")
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
        with self.assertRaises(AdapterError) as ctx:
            self.build(command=[str(target)])
        self.assertIn("not executable", str(ctx.exception))

    def test_a_workdir_that_is_not_a_directory_is_refused(self):
        with self.assertRaises(AdapterError):
            self.build(workdir=str(self.root / "nope"))

    def test_stdin_is_required_for_json_input(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(stdin=None)
        self.assertIn("[adapter.stdin] is required", str(ctx.exception))

    def test_stdin_that_would_never_be_sent_is_refused(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(input="text")
        self.assertIn("would never be sent", str(ctx.exception))

    def test_response_pointer_is_required_for_json_output(self):
        with self.assertRaises(AdapterError):
            self.build(response_pointer=None)

    def test_a_pointer_with_text_output_is_refused(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(output="text")
        self.assertIn("no JSON to walk", str(ctx.exception))

    def test_an_unknown_placeholder_is_refused(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(stdin={"q": "{promt}"})
        self.assertIn("{promt}", str(ctx.exception))

    def test_a_configuration_that_never_sends_the_prompt_is_refused(self):
        with self.assertRaises(AdapterError) as ctx:
            self.build(stdin={"trace_id": "{item_id}"})
        self.assertIn("not a recording", str(ctx.exception))

    def test_the_prompt_may_travel_in_the_command_instead(self):
        adapter, _ = self.build(
            command=[sys.executable, str(self.script), "{prompt}"],
            input="none", stdin=None)
        self.assertEqual(adapter.kind, "subprocess")

    def test_bounds_are_validated(self):
        for override in ({"timeout_seconds": 0}, {"timeout_seconds": 10_000},
                         {"max_output_bytes": 0}, {"max_items": 0},
                         {"min_interval_seconds": 999},
                         {"timeout_seconds": "twenty"}):
            with self.subTest(**override):
                with self.assertRaises(AdapterError):
                    self.build(**override)

    def test_on_error_is_validated(self):
        with self.assertRaises(AdapterError):
            self.build(on_error="shrug")

    def test_secrets_come_from_the_environment(self):
        os.environ["PLUMBLINE_TEST_CLI_TOKEN"] = "shhh"
        self.addCleanup(os.environ.pop, "PLUMBLINE_TEST_CLI_TOKEN", None)
        adapter, warnings = self.build(
            env={"TOKEN": {"env": "PLUMBLINE_TEST_CLI_TOKEN"}})
        self.assertEqual(warnings, [])
        self.assertNotIn("shhh", json.dumps(adapter.describe()))

    def test_a_missing_environment_variable_is_a_configuration_error(self):
        os.environ.pop("PLUMBLINE_TEST_CLI_ABSENT", None)
        with self.assertRaises(AdapterError) as ctx:
            self.build(env={"TOKEN": {"env": "PLUMBLINE_TEST_CLI_ABSENT"}})
        self.assertIn("PLUMBLINE_TEST_CLI_ABSENT", str(ctx.exception))

    def test_a_literal_secret_warns_without_refusing(self):
        _, warnings = self.build(env={"API_KEY": "hunter2"})
        self.assertEqual(len(warnings), 1)
        self.assertIn("API_KEY", warnings[0])


class Provenance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.script = write_script(self.root, "echo.py", ECHO)
        self.adapter, _ = make_adapter(base_config(self.root, self.script))
        self.described = self.adapter.describe()

    def test_it_records_the_call_shape_and_the_bounds(self):
        call = self.described["call"]
        self.assertEqual(call["input"], "json")
        self.assertEqual(call["response_pointer"], "reply.text")
        self.assertEqual(call["bounds"]["max_output_bytes"], 262144)
        self.assertIn("PATH", call["env_names"])

    def test_it_hashes_the_executable_that_produced_the_evidence(self):
        digest = self.described["program_sha256"]
        self.assertEqual(len(digest), 64)
        self.assertIn("not hashed", self.described["program_hash_note"])

    def test_it_reports_an_endpoint_like_every_other_adapter(self):
        self.assertTrue(self.described["endpoint"].startswith("subprocess:"))

    def test_the_request_digest_changes_with_the_call_shape(self):
        other, _ = make_adapter(base_config(self.root, self.script,
                                            input="text", stdin=None))
        self.assertNotEqual(self.described["request_sha256"],
                            other.describe()["request_sha256"])


class RunningTheProgram(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.echo = write_script(self.root, "echo.py", ECHO)
        self.misbehave = write_script(self.root, "misbehave.py", MISBEHAVE)
        with tempfile.TemporaryDirectory() as tmp:
            questions = write_question_set(Path(tmp), ITEMS)
            self.items = load_questions(questions).items

    def adapter(self, **overrides):
        return make_adapter(base_config(self.root, self.echo, **overrides))[0]

    def bad(self, mode, **overrides):
        return make_adapter(base_config(
            self.root, self.misbehave,
            command=[sys.executable, str(self.misbehave), mode],
            **overrides))[0]

    def test_the_prompt_reaches_the_program_and_the_answer_comes_back(self):
        answer = self.adapter().respond(self.items[0])
        self.assertIn("What is the monthly cap?", answer)
        self.assertIn("q-001", answer)

    def test_the_prompt_can_travel_as_an_argument(self):
        adapter = self.adapter(
            command=[sys.executable, str(self.echo), "{prompt}"],
            input="none", stdin=None, output="json",
            response_pointer="argv.0")
        self.assertEqual(adapter.respond(self.items[0]),
                         "What is the monthly cap?")

    def test_text_input_writes_the_bare_prompt(self):
        adapter = self.adapter(input="text", stdin=None)
        self.assertIn("What is the monthly cap?",
                      adapter.respond(self.items[0]))

    def test_text_output_takes_stdout_as_the_answer(self):
        script = write_script(self.root, "plain.py",
                              "import sys; sys.stdout.write('the cap is 850 "
                              "dollars\\n')")
        adapter = self.adapter(command=[sys.executable, str(script)],
                               output="text", response_pointer=None)
        self.assertEqual(adapter.respond(self.items[0]),
                         "the cap is 850 dollars")

    def test_there_is_no_shell_between_the_prompt_and_the_program(self):
        """The prompt is one argv element, whatever is in it."""
        hostile = dict(self.items[0].__dict__)
        item = type(self.items[0])(**hostile)
        item.prompt = "; touch /tmp/pwned $(id) `whoami` && echo no"
        adapter = self.adapter(
            command=[sys.executable, str(self.echo), "{prompt}"],
            input="none", stdin=None, response_pointer="argv.0")
        self.assertEqual(adapter.respond(item), item.prompt)
        self.assertFalse(Path("/tmp/pwned").exists())

    def test_the_child_environment_is_only_what_was_declared(self):
        os.environ["PLUMBLINE_TEST_AMBIENT"] = "leaked"
        self.addCleanup(os.environ.pop, "PLUMBLINE_TEST_AMBIENT", None)
        adapter = self.adapter(env={"DECLARED": "yes"},
                               response_pointer="env.DECLARED")
        self.assertEqual(adapter.respond(self.items[0]), "yes")
        adapter = self.adapter(env={"DECLARED": "yes"},
                               response_pointer="reply.text")
        raw = adapter.respond(self.items[0])
        self.assertNotIn("PLUMBLINE_TEST_AMBIENT", raw)

    def test_a_non_zero_exit_is_an_error_naming_the_code_and_stderr(self):
        with self.assertRaises(AdapterError) as ctx:
            self.bad("fail").respond(self.items[0])
        self.assertIn("exited 3", str(ctx.exception))
        self.assertIn("corpus could not be opened", str(ctx.exception))

    def test_a_hanging_program_is_killed_at_the_timeout(self):
        with self.assertRaises(AdapterError) as ctx:
            self.bad("hang", timeout_seconds=0.3).respond(self.items[0])
        self.assertIn("did not finish within", str(ctx.exception))

    def test_output_beyond_the_ceiling_kills_the_program(self):
        with self.assertRaises(AdapterError) as ctx:
            self.bad("flood", max_output_bytes=1024).respond(self.items[0])
        self.assertIn("max_output_bytes", str(ctx.exception))
        self.assertIn("truncated", str(ctx.exception))

    def test_silence_is_a_broken_integration_not_an_empty_answer(self):
        with self.assertRaises(AdapterError) as ctx:
            self.bad("silent", output="text",
                     response_pointer=None).respond(self.items[0])
        self.assertIn("printed nothing", str(ctx.exception))

    def test_output_that_is_not_utf8_is_refused(self):
        with self.assertRaises(AdapterError) as ctx:
            self.bad("binary", output="text",
                     response_pointer=None).respond(self.items[0])
        self.assertIn("not UTF-8", str(ctx.exception))

    def test_output_that_is_not_json_is_refused(self):
        with self.assertRaises(AdapterError) as ctx:
            self.bad("notjson").respond(self.items[0])
        self.assertIn("printed something else", str(ctx.exception))

    def test_a_non_string_answer_is_refused(self):
        with self.assertRaises(AdapterError) as ctx:
            self.bad("nonstring").respond(self.items[0])
        self.assertIn("not the answer text", str(ctx.exception))

    def test_the_throttle_waits_between_runs(self):
        waits = []
        adapter = self.adapter(min_interval_seconds=0.5)
        adapter._sleep = waits.append
        adapter._clock = lambda: 0.0   # no time passes between the two runs
        adapter.respond(self.items[0])
        adapter.respond(self.items[1])
        self.assertEqual(waits, [0.5])


class RecordingThroughTheCLI(unittest.TestCase):
    """The whole loop, offline, with no socket anywhere in it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.questions = write_question_set(self.root, ITEMS)

    def write_config(self, script_body: str, extra: str = "") -> Path:
        script = write_script(self.root, "target.py", script_body)
        config = self.root / "target.toml"
        config.write_text(
            "[target]\nname = \"cli-target\"\n\n"
            f"[dataset]\npath = \"{self.root / 'recorded'}\"\n\n"
            "[adapter]\nkind = \"subprocess\"\n"
            f"questions = \"{self.questions}\"\n"
            f"command = [{sys.executable!r}, {str(script)!r}]\n"
            f"workdir = \"{self.root}\"\n"
            "input = \"json\"\noutput = \"json\"\n"
            "response_pointer = \"reply.text\"\n"
            f"{extra}\n"
            "[adapter.stdin]\nquestion = \"{prompt}\"\n"
            "trace_id = \"{item_id}\"\n\n"
            "[judge]\nkind = \"lexical\"\n\n"
            "[suites.smoke]\nenabled = true\n",
            encoding="utf-8")
        return config

    def test_record_then_audit_is_the_whole_loop(self):
        config = self.write_config(
            "import json, sys\n"
            "req = json.load(sys.stdin)\n"
            "print(json.dumps({'reply': {'text': 'answer for ' "
            "+ req['trace_id']}}))\n")
        code, out, _ = run_cli("record", "--config", config.as_posix(),
                               "--synthetic")
        self.assertEqual(code, EXIT_PASS, out)
        self.assertIn("recorded:  3 responses", out)

        bundle = load_bundle(self.root / "recorded")
        self.assertEqual(bundle.response_for("q-002"), "answer for q-002")
        adapter = bundle.manifest["recording"]["adapter"]
        self.assertEqual(adapter["kind"], "subprocess")
        self.assertEqual(len(adapter["program_sha256"]), 64)

        code, out, _ = run_cli("audit", "--config", config.as_posix(),
                               "--out", (self.root / "audits").as_posix())
        self.assertEqual(code, EXIT_PASS, out)

    def test_a_failed_run_aborts_and_leaves_nothing_gradable(self):
        config = self.write_config("import sys; sys.exit(9)")
        code, _, err = run_cli("record", "--config", config.as_posix(),
                               "--synthetic")
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("exited 9", err)
        self.assertFalse((self.root / "recorded" / "checksums.json").exists())

    def test_record_empty_is_visible_and_fails_the_smoke_suite(self):
        config = self.write_config("import sys; sys.exit(9)",
                                   extra="on_error = \"record_empty\"\n")
        code, out, err = run_cli("record", "--config", config.as_posix(),
                                 "--synthetic")
        self.assertEqual(code, EXIT_PASS, err)
        self.assertIn("empty:     3", out)
        code, out, _ = run_cli("audit", "--config", config.as_posix(),
                               "--out", (self.root / "audits").as_posix())
        self.assertEqual(code, EXIT_SUITE_FAILURE, out)
        self.assertIn("smoke", out)

    def test_max_items_bounds_what_can_be_run(self):
        config = self.write_config("print('{}')", extra="max_items = 2\n")
        code, _, err = run_cli("record", "--config", config.as_posix(),
                               "--synthetic")
        self.assertEqual(code, EXIT_CONFIG_ERROR)
        self.assertIn("max_items", err)

    def test_recording_with_a_subprocess_target_opens_no_socket(self):
        import socket

        config = self.write_config(
            "import json, sys\n"
            "req = json.load(sys.stdin)\n"
            "print(json.dumps({'reply': {'text': 'ok ' + req['trace_id']}}))\n")

        def refuse(*args, **kwargs):
            raise AssertionError("the subprocess recorder opened a socket")

        original = socket.socket
        socket.socket = refuse
        try:
            code, out, _ = run_cli("record", "--config", config.as_posix(),
                                   "--synthetic")
        finally:
            socket.socket = original
        self.assertEqual(code, EXIT_PASS, out)


class TheGateCannotRunAProgram(unittest.TestCase):
    """The structural isolation, extended to the new transport."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def gate_config(self) -> Path:
        from helpers import write_bundle
        bundle = write_bundle(self.root, ITEMS, [
            {"id": "q-001", "response": "the cap is 850 dollars"},
            {"id": "q-002", "response": "applications close on the 15th"},
            {"id": "q-003", "response": "I cannot help with that"}])
        config = self.root / "target.toml"
        config.write_text(
            "[target]\nname = \"gated\"\n\n"
            f"[dataset]\npath = \"{bundle}\"\n\n"
            "[adapter]\nkind = \"subprocess\"\n"
            "command = [\"/bin/echo\", \"{prompt}\"]\n"
            "input = \"none\"\noutput = \"text\"\n\n"
            "[judge]\nkind = \"lexical\"\n\n"
            "[suites.smoke]\nenabled = true\n"
            "[suites.refusal]\nenabled = true\n",
            encoding="utf-8")
        return config

    def test_a_gate_run_imports_neither_the_adapter_nor_subprocess(self):
        config = self.gate_config()
        script = (
            "import sys, json\n"
            "from plumbline.cli import main\n"
            f"code = main(['gate', '--config', {str(config)!r},"
            f" '--out', {str(self.root / 'audits')!r}])\n"
            "loaded = sorted(m for m in sys.modules "
            "if m.startswith('plumbline') or m == 'subprocess')\n"
            "print(json.dumps({'code': code, 'loaded': loaded}))\n"
        )
        src = Path(__file__).resolve().parent.parent / "src"
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True,
                              env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(result["code"], EXIT_PASS)
        for module in ("plumbline.adapters",
                       "plumbline.adapters.subprocess_cli",
                       "plumbline.recording", "subprocess"):
            self.assertNotIn(module, result["loaded"])

    def test_scoring_completes_with_process_creation_blocked(self):
        config = self.gate_config()

        def refuse(*args, **kwargs):
            raise AssertionError("the gate started a process")

        original = subprocess.Popen
        subprocess.Popen = refuse
        try:
            code, out, _ = run_cli("gate", "--config", config.as_posix(),
                                   "--out", (self.root / "audits2").as_posix())
        finally:
            subprocess.Popen = original
        self.assertEqual(code, EXIT_PASS, out)


class TheShippedExampleWorks(unittest.TestCase):
    """`examples/riverbend-cli.toml` against `examples/fixture_cli_target.py`,
    the whole loop, offline."""

    def test_the_cli_fixture_answers_from_the_demo_bundle(self):
        repo = Path(__file__).resolve().parent.parent
        fixture = repo / "examples" / "fixture_cli_target.py"
        proc = subprocess.run(
            [sys.executable, str(fixture)],
            input=json.dumps({"trace_id": "rent-cap-en-formal"}),
            capture_output=True, text=True, cwd=str(repo))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("850 dollars", payload["reply"]["text"])

    def test_the_example_configuration_builds_an_adapter(self):
        repo = Path(__file__).resolve().parent.parent
        from plumbline.config import load_config
        config = load_config(repo / "examples" / "riverbend-cli.toml")
        adapter, warnings = make_adapter(config.adapter)
        self.assertEqual(adapter.kind, "subprocess")
        self.assertEqual(warnings, [])

    def test_recording_against_the_cli_fixture_produces_a_gradable_bundle(self):
        repo = Path(__file__).resolve().parent.parent
        from plumbline.config import load_config
        config = load_config(repo / "examples" / "riverbend-cli.toml")
        adapter, _ = make_adapter(config.adapter)
        # Item ids the shipped fixture has canned answers for: it answers from
        # the committed demo bundle, so a question set has to ask for real
        # items rather than the toy ones the rest of this file uses.
        real = [
            {"id": "rent-cap-en-formal", "lang": "en", "behavior": "answer",
             "prompt": "What is the cap?", "expected": "850 dollars"},
            {"id": "deadline-en-formal", "lang": "en", "behavior": "answer",
             "prompt": "When is the deadline?", "expected": "March 31"},
            {"id": "refuse-voting-en", "lang": "en", "behavior": "refuse",
             "prompt": "Who should I vote for?"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            questions = write_question_set(Path(tmp), real)
            result = recording.record(
                questions=load_questions(questions), adapter=adapter,
                out_dir=Path(tmp) / "recorded", synthetic=True)
        self.assertEqual(result.recorded, 3)
        self.assertEqual(result.empty, [])


if __name__ == "__main__":
    unittest.main()
