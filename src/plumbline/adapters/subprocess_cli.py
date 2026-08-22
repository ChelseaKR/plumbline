"""`subprocess`: record against a target that is a local program.

The HTTP adapter assumes the system under test is a service somewhere. Plenty
of systems worth grading are not: a command-line assistant, a batch scorer, a
wrapper somebody wrote around a model, a binary a vendor shipped. For those,
a subprocess adapter fits Plumbline's offline-first default better than HTTP
does — the whole recording happens on one machine with no socket open at all.

```toml
[adapter]
kind = "subprocess"
command = ["python3", "navigator.py", "--lang", "{lang}"]
workdir = "../navigator"
input = "json"                 # "json", "text" or "none"
output = "json"                # "json" or "text"
response_pointer = "reply.text"
timeout_seconds = 20
max_output_bytes = 262144
min_interval_seconds = 0.0
max_items = 100
on_error = "abort"

[adapter.stdin]                # the JSON written to the program's stdin
question = "{prompt}"
locale = "{lang}"

[adapter.env]                  # the program's entire environment, plus PATH
LANG = "C.UTF-8"
NAVIGATOR_TOKEN = { env = "NAVIGATOR_TOKEN" }
```

**There is no shell.** `command` is an argv list and is executed directly; a
string is refused with an explanation rather than split or handed to `sh`.
Interpolation happens element by element, so a prompt containing `;`, `$(…)`
or a newline is one argument and stays one argument. There is no `shell` key
to set, and an unrecognised key is refused, so there is no way to ask for one.

**It is not a sandbox, and this file will not pretend otherwise.** The program
runs with the privileges of whoever ran `plumbline record`. What the adapter
gives you is bounds and provenance: an explicit timeout, an explicit output
ceiling enforced by killing the child, an explicit environment, and a recorded
hash of the executable that produced the evidence. If the program is not
trusted, that is a decision to make before pointing a recorder at it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import cast

from .. import network
from ..bundle import Item
from ..hashing import canonical_json, sha256_text
from . import AdapterError

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 900.0
DEFAULT_MAX_OUTPUT_BYTES = 262144          # 256 KiB
MAX_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
STDERR_CAPTURE_BYTES = 4096                # only ever quoted in an error
MAX_MIN_INTERVAL_SECONDS = 60.0
DEFAULT_MAX_ITEMS = 250
CEILING_MAX_ITEMS = 100_000
POLL_SECONDS = 0.01

TEMPLATE_KEYS = ("prompt", "lang", "item_id")
INPUT_MODES = ("json", "text", "none")
OUTPUT_MODES = ("json", "text")

KNOWN_KEYS = frozenset({
    "kind", "questions", "command", "workdir", "env", "input", "stdin",
    "output", "response_pointer", "timeout_seconds", "max_output_bytes",
    "min_interval_seconds", "max_items", "on_error",
})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounded(value, *, name, default, low, high, kind=float):
    if value is None:
        return kind(default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterError(f"[adapter].{name} must be a number (got {value!r})")
    value = kind(value)
    if not (low <= value <= high):
        raise AdapterError(
            f"[adapter].{name} must be between {low} and {high} (got {value})")
    return value


class SubprocessAdapter:
    kind = "subprocess"

    def __init__(self, *, command: list[str], program: Path, workdir: Path,
                 env: dict[str, str], input_mode: str, stdin_template,
                 output_mode: str, response_pointer: str | None,
                 timeout_seconds: float, max_output_bytes: int,
                 min_interval_seconds: float, max_items: int, on_error: str,
                 sleep=time.sleep, clock=time.monotonic):
        self._command = command
        self._program = program
        self._workdir = workdir
        self._env = env
        self._input_mode = input_mode
        self._stdin_template = stdin_template
        self._output_mode = output_mode
        self._response_pointer = response_pointer
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self._min_interval = min_interval_seconds
        self.max_items = max_items
        self.on_error = on_error
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    # --- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict) -> tuple["SubprocessAdapter", list[str]]:
        unknown = sorted(set(cfg) - KNOWN_KEYS)
        if unknown:
            raise AdapterError(
                f"[adapter] has key(s) the subprocess adapter does not "
                f"understand: {', '.join(unknown)}. Refused rather than "
                f"ignored — a misspelled bound is a bound that is not there."
                + (" There is deliberately no `shell` option: the command is "
                   "an argv list and is executed directly."
                   if "shell" in unknown else "")
            )

        command = cfg.get("command")
        if isinstance(command, str):
            raise AdapterError(
                "[adapter].command must be a list of arguments, not a string. "
                "Plumbline never runs a shell, so there is nothing to split "
                "the string safely: write [\"python3\", \"navigator.py\", "
                "\"--json\"] and a prompt containing a semicolon stays one "
                "argument."
            )
        if (not isinstance(command, list) or not command
                or not all(isinstance(part, str) and part for part in command)):
            raise AdapterError(
                "[adapter].command is required: the argv of the program under "
                "test, for example [\"./navigator\", \"--json\"]"
            )

        workdir = Path(cfg.get("workdir") or Path.cwd())
        if not workdir.is_dir():
            raise AdapterError(
                f"[adapter].workdir is not a directory: {workdir}")

        program = cls._resolve_program(command[0], workdir)

        input_mode = cfg.get("input", "json")
        if input_mode not in INPUT_MODES:
            raise AdapterError(
                f"[adapter].input must be one of {', '.join(INPUT_MODES)}: "
                f"\"json\" writes [adapter.stdin] to the program, \"text\" "
                f"writes the bare prompt, \"none\" writes nothing and the "
                f"prompt must then be in the command"
            )
        stdin_template = cfg.get("stdin")
        if input_mode == "json":
            if not isinstance(stdin_template, dict) or not stdin_template:
                raise AdapterError(
                    "[adapter.stdin] is required when input = \"json\": it is "
                    "the JSON object written to the program's stdin, with "
                    "{prompt} where the item's prompt goes"
                )
        elif stdin_template is not None:
            raise AdapterError(
                f"[adapter.stdin] is set but input = {input_mode!r}, so it "
                f"would never be sent. Refused rather than ignored."
            )

        placeholders = network.placeholders_in(command)
        if input_mode == "json":
            placeholders |= network.placeholders_in(stdin_template)
        unknown_holes = sorted(placeholders - set(TEMPLATE_KEYS))
        if unknown_holes:
            raise AdapterError(
                f"unknown placeholder(s) "
                f"{', '.join('{' + u + '}' for u in unknown_holes)}; "
                f"available: {', '.join('{' + k + '}' for k in TEMPLATE_KEYS)}"
            )
        if "prompt" not in placeholders and input_mode != "text":
            raise AdapterError(
                "nothing in this configuration carries the item's prompt to "
                "the program: use {prompt} in [adapter].command or in "
                "[adapter.stdin], or set input = \"text\". Every item would "
                "otherwise send the same request, and that is not a recording."
            )

        output_mode = cfg.get("output", "json")
        if output_mode not in OUTPUT_MODES:
            raise AdapterError(
                f"[adapter].output must be one of {', '.join(OUTPUT_MODES)}")
        pointer = cfg.get("response_pointer")
        if output_mode == "json":
            if not isinstance(pointer, str) or not pointer:
                raise AdapterError(
                    "[adapter].response_pointer is required when output = "
                    "\"json\": the dotted path to the answer text in what the "
                    "program prints, for example \"reply.text\""
                )
        elif pointer is not None:
            raise AdapterError(
                "[adapter].response_pointer is set but output = \"text\", so "
                "there is no JSON to walk. Refused rather than ignored."
            )

        try:
            declared, warnings = network.resolve_headers(
                cfg.get("env"), where="[adapter.env]")
        except network.OutboundConfigError as e:
            raise AdapterError(f"[adapter]: {e}") from e
        env = cls._child_environment(declared)

        timeout = _bounded(cfg.get("timeout_seconds"), name="timeout_seconds",
                           default=DEFAULT_TIMEOUT_SECONDS, low=0.1,
                           high=MAX_TIMEOUT_SECONDS)
        max_output = _bounded(cfg.get("max_output_bytes"),
                              name="max_output_bytes",
                              default=DEFAULT_MAX_OUTPUT_BYTES, low=1,
                              high=MAX_MAX_OUTPUT_BYTES, kind=int)
        min_interval = _bounded(cfg.get("min_interval_seconds"),
                                name="min_interval_seconds", default=0.0,
                                low=0.0, high=MAX_MIN_INTERVAL_SECONDS)
        max_items = _bounded(cfg.get("max_items"), name="max_items",
                             default=DEFAULT_MAX_ITEMS, low=1,
                             high=CEILING_MAX_ITEMS, kind=int)
        if not isinstance(cfg.get("max_items", 1), int) or isinstance(
                cfg.get("max_items"), bool):
            raise AdapterError("[adapter].max_items must be a whole number")

        on_error = cfg.get("on_error", "abort")
        if on_error not in ("abort", "record_empty"):
            raise AdapterError(
                "[adapter].on_error must be \"abort\" (default: a failed run "
                "stops the recording) or \"record_empty\" (record an empty "
                "answer, which the smoke suite then fails on)"
            )

        return cls(
            command=list(command), program=program, workdir=workdir, env=env,
            input_mode=input_mode, stdin_template=stdin_template,
            output_mode=output_mode, response_pointer=pointer,
            timeout_seconds=timeout, max_output_bytes=max_output,
            min_interval_seconds=min_interval, max_items=max_items,
            on_error=on_error,
        ), warnings

    @staticmethod
    def _resolve_program(name: str, workdir: Path) -> Path:
        """Find the executable, so a typo is a configuration error rather than
        an OSError halfway through a recording — and so its bytes can be
        hashed into the evidence."""
        candidate = Path(name)
        if not candidate.is_absolute() and (os.sep in name or "/" in name):
            candidate = (workdir / candidate).resolve()
        found = (str(candidate) if candidate.is_file()
                 else shutil.which(name))
        if not found:
            raise AdapterError(
                f"[adapter].command names a program that is not there: "
                f"{name!r} is neither a file (relative to the working "
                f"directory) nor on PATH"
            )
        path = Path(found)
        if not os.access(path, os.X_OK):
            raise AdapterError(f"[adapter].command: {name!r} is not executable")
        return path

    @staticmethod
    def _child_environment(declared: dict[str, str]) -> dict[str, str]:
        """The program's whole environment: PATH, plus exactly what the config
        declares.

        Inheriting the caller's environment would make a recording depend on
        ambient state nobody wrote down, which is the opposite of evidence
        somebody can defend. PATH is the one exception, because a program that
        cannot find the tools it shells out to is a support burden rather than
        a security boundary — and this is not a security boundary. The
        variable *names* go in the manifest; the values never do.
        """
        env = {"PATH": os.environ.get("PATH", os.defpath)}
        env.update(declared)
        return env

    # --- provenance ---------------------------------------------------------

    def _call_shape(self) -> dict:
        return {
            "command": list(self._command),
            "input": self._input_mode,
            "stdin_template": self._stdin_template,
            "output": self._output_mode,
            "response_pointer": self._response_pointer,
            "env_names": sorted(self._env),
            "bounds": {
                "timeout_seconds": self.timeout_seconds,
                "max_output_bytes": self.max_output_bytes,
            },
        }

    def describe(self) -> dict:
        """What goes into the recorded bundle's manifest.

        `program_sha256` is the part an HTTP recording cannot have: the exact
        bytes of the executable that produced this evidence. It is not a
        complete answer — hashing `python3` says nothing about the script it
        ran, and the script is named in `command` but not hashed — and saying
        so here is better than implying it pins the whole target.

        No absolute paths: a manifest is committed evidence and one machine's
        directory layout is not a fact about the system under test. Environment
        variable *names* are recorded; values never are.
        """
        shape = self._call_shape()
        return {
            "kind": self.kind,
            # Every adapter reports an `endpoint`, so reports and `validate`
            # can say where evidence came from without knowing the transport.
            # For a local program, the program is the endpoint.
            "endpoint": f"subprocess:{self._program.name}",
            "request_sha256": sha256_text(canonical_json(shape)),
            "call": shape,
            "program": self._program.name,
            "program_sha256": _sha256_file(self._program),
            "program_hash_note": (
                "sha256 of the executable in command[0]. An interpreter names "
                "its script in the command but the script itself is not hashed"
            ),
            "min_interval_seconds": self._min_interval,
            "on_error": self.on_error,
        }

    # --- recording ----------------------------------------------------------

    def respond(self, item: Item) -> str:
        self._throttle()
        values = {"prompt": item.prompt, "lang": item.lang, "item_id": item.id}
        try:
            # fill_template's signature is object -> object because it also
            # fills JSON request bodies of arbitrary shape (see network.py);
            # substituting into a list[str] argv always yields a list[str]
            # back, which the generic signature can't express on its own.
            argv = cast("list[str]", network.fill_template(self._command, values))
            payload = self._stdin_bytes(values)
        except network.OutboundConfigError as e:
            raise AdapterError(f"item '{item.id}': {e}") from e

        stdout, stderr, code, outcome = self._run(argv, payload)
        if outcome == "timeout":
            raise AdapterError(
                f"item '{item.id}': {self._program.name} did not finish within "
                f"{self.timeout_seconds}s and was killed. A recorder that "
                f"waits forever is a recorder that never fails."
            )
        if outcome == "too_much_output":
            raise AdapterError(
                f"item '{item.id}': {self._program.name} wrote more than "
                f"max_output_bytes ({self.max_output_bytes}) and was killed; "
                f"refusing to grade a truncated answer"
            )
        if code != 0:
            raise AdapterError(
                f"item '{item.id}': {self._program.name} exited {code}"
                + (f": {self._snippet(stderr)}" if stderr else "")
            )
        try:
            text = stdout.decode("utf-8")
        except UnicodeDecodeError as e:
            raise AdapterError(
                f"item '{item.id}': the program's output is not UTF-8 ({e})"
            ) from e
        return self._answer(item, text, stderr)

    def _stdin_bytes(self, values: dict[str, str]) -> bytes | None:
        if self._input_mode == "none":
            return None
        if self._input_mode == "text":
            return values["prompt"].encode("utf-8")
        body = network.fill_template(self._stdin_template, values)
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _answer(self, item: Item, text: str, stderr: bytes) -> str:
        if self._output_mode == "text":
            answer = text.strip()
            if not answer:
                raise AdapterError(
                    f"item '{item.id}': {self._program.name} exited 0 and "
                    f"printed nothing"
                    + (f" (stderr: {self._snippet(stderr)})" if stderr else "")
                    + ". That is a broken integration, not an empty answer; "
                      "set on_error = \"record_empty\" if you want the smoke "
                      "suite to score it instead."
                )
            return answer
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise AdapterError(
                f"item '{item.id}': output = \"json\" but the program printed "
                f"something else ({e}): {self._snippet(text.encode('utf-8'))}"
            ) from e
        # `from_config` refuses to build an adapter with output = "json" and
        # no response_pointer, and `_answer` only reaches this branch when
        # `self._output_mode != "text"` (checked above) — i.e. "json". mypy
        # cannot see either guard from here; the None case is unreachable.
        assert self._response_pointer is not None
        try:
            value = network.resolve_pointer(payload, self._response_pointer)
        except network.OutboundError as e:
            raise AdapterError(f"item '{item.id}': {e}") from e
        if not isinstance(value, str):
            raise AdapterError(
                f"item '{item.id}': the value at "
                f"'{self._response_pointer}' is {type(value).__name__}, not "
                f"the answer text"
            )
        return value

    @staticmethod
    def _snippet(raw: bytes, limit: int = 200) -> str:
        text = raw.decode("utf-8", errors="replace").strip().replace("\n", " ")
        return text[:limit] + ("…" if len(text) > limit else "")

    def _run(self, argv: list[str], payload: bytes | None):
        """One bounded run. Returns (stdout, stderr, returncode, outcome).

        The output ceiling is enforced by *killing the child*, not by
        truncating after the fact: a program that decides to print a gigabyte
        should cost the recorder one refusal, not the machine's memory. Reader
        threads keep both pipes drained so the child cannot deadlock on a full
        one, and the deadline is checked by polling rather than by `select`,
        which keeps this the same code on every platform Python runs on.
        """
        try:
            proc = subprocess.Popen(
                argv, cwd=str(self._workdir), env=self._env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as e:
            raise AdapterError(f"could not run {argv[0]!r}: {e}") from e

        stdout, stderr = bytearray(), bytearray()
        overflowed = threading.Event()

        def pump(stream, sink: bytearray, cap: int, on_overflow):
            try:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        return
                    sink += chunk
                    if len(sink) > cap:
                        on_overflow()
                        return
            except (OSError, ValueError):
                return

        readers = [
            threading.Thread(target=pump, daemon=True,
                             args=(proc.stdout, stdout, self.max_output_bytes,
                                   overflowed.set)),
            threading.Thread(target=pump, daemon=True,
                             args=(proc.stderr, stderr, STDERR_CAPTURE_BYTES,
                                   lambda: None)),
            threading.Thread(target=self._write_stdin, daemon=True,
                             args=(proc, payload)),
        ]
        for reader in readers:
            reader.start()

        deadline = self._clock() + self.timeout_seconds
        outcome = "ok"
        while True:
            if proc.poll() is not None:
                break
            if overflowed.is_set():
                outcome = "too_much_output"
                break
            if self._clock() >= deadline:
                outcome = "timeout"
                break
            time.sleep(POLL_SECONDS)
        if outcome != "ok":
            proc.kill()
            proc.wait()
        for reader in readers:
            reader.join(timeout=1.0)
        for stream in (proc.stdout, proc.stderr):
            # Popen's type covers the case where the pipe was never
            # requested; this Popen call always passes stdout=PIPE and
            # stderr=PIPE, so both are real streams, never None.
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass
        return bytes(stdout), bytes(stderr), proc.returncode, outcome

    @staticmethod
    def _write_stdin(proc, payload: bytes | None) -> None:
        try:
            # This Popen call always passes stdin=PIPE, so proc.stdin is
            # always a real stream, never None; a closed or broken pipe
            # surfaces as OSError/ValueError below, not as this being None.
            assert proc.stdin is not None
            if payload is not None:
                proc.stdin.write(payload)
            proc.stdin.close()
        except (OSError, ValueError):
            # The program closed stdin, or was killed. Either way what it did
            # with the input is judged by what it printed.
            pass

    def _throttle(self) -> None:
        if not self._min_interval:
            return
        now = self._clock()
        if self._last_call is not None:
            wait = self._min_interval - (now - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()
