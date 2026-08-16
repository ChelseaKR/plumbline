"""Shared test fixtures: small evidence bundles, and a real local HTTP server
for the code paths that talk to a target."""

from __future__ import annotations

import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from plumbline import suites as suite_registry
from plumbline.bundle import seal


class LocalJSONServer:
    """A real HTTP server on the loopback interface.

    The adapter and the model judge are only worth anything if they work over
    a socket, so the tests give them one rather than a mocked opener. Bound to
    127.0.0.1 on an ephemeral port, torn down with the context manager.

    `handler(request) -> (status, payload)` receives a dict with `path`,
    `method`, `headers` and the decoded JSON `body`, and returns an HTTP
    status and an object to serialise (or raw bytes, to test malformed
    responses).
    """

    def __init__(self, handler):
        self._handler = handler
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _dispatch(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else None
                except (UnicodeDecodeError, json.JSONDecodeError):
                    body = None
                request = {"path": self.path, "method": self.command,
                           "headers": dict(self.headers), "body": body,
                           "raw": raw}
                outer.requests.append(request)
                status, payload = outer._handler(request)
                if isinstance(payload, bytes):
                    data = payload
                else:
                    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                if status in (301, 302, 307, 308):
                    self.send_header("Location", "http://127.0.0.1:1/elsewhere")
                self.end_headers()
                self.wfile.write(data)

            do_GET = _dispatch
            do_POST = _dispatch

            def log_message(self, *args):  # keep the test output readable
                pass

        class QuietServer(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                # A client that timed out and hung up is the behaviour under
                # test, not a test failure worth a traceback.
                pass

        self._server = QuietServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> "LocalJSONServer":
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def unused_url() -> str:
    """A loopback URL nothing is listening on: the unreachable-target case."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/unreachable"


@contextlib.contextmanager
def temporary_skeleton_suite(suite_id: str = "not_built_yet"):
    """Register an unimplemented suite for the duration of a test.

    The registry's refusal to enable an unimplemented suite is permanent
    behavior, but the shipped skeleton list empties as suites land, so the
    tests supply their own subject rather than depending on something staying
    unbuilt.
    """
    suite_registry.available()  # force the registry to load

    class NotBuiltYetSuite(suite_registry.Suite):
        id = suite_id
        implemented = False
        planned_milestone = "never (test fixture)"

    suite_registry.register(NotBuiltYetSuite)
    try:
        yield suite_id
    finally:
        suite_registry._REGISTRY.pop(suite_id, None)


def write_bundle(
    root: Path,
    items: list[dict],
    responses: list[dict],
    *,
    name: str = "test-bundle",
    sources: list[dict] | None = None,
    interface: str | None = None,
    do_seal: bool = True,
) -> Path:
    bundle_dir = Path(root) / name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    files = {"items": "items.jsonl", "responses": "responses.jsonl"}
    if sources is not None:
        files["sources"] = "sources.jsonl"
        (bundle_dir / "sources.jsonl").write_text(
            "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in sources),
            encoding="utf-8",
        )
    if interface is not None:
        files["interface"] = "interface.html"
        (bundle_dir / "interface.html").write_text(interface, encoding="utf-8")
    manifest = {
        "format": "plumbline-bundle",
        "format_version": 1,
        "name": name,
        "version": "0.0.1",
        "synthetic": True,
        "description": "synthetic fixture for tests",
        "files": files,
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (bundle_dir / "items.jsonl").write_text(
        "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8"
    )
    (bundle_dir / "responses.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in responses), encoding="utf-8"
    )
    if do_seal:
        seal(bundle_dir)
    return bundle_dir


def answer_item(item_id: str, expected: str, **extra) -> dict:
    return {
        "id": item_id, "lang": "en", "behavior": "answer",
        "prompt": f"prompt for {item_id}", "expected": expected, **extra,
    }


def refuse_item(item_id: str, **extra) -> dict:
    return {
        "id": item_id, "lang": "en", "behavior": "refuse",
        "prompt": f"prompt for {item_id}", **extra,
    }


def response(item_id: str, text: str) -> dict:
    return {"id": item_id, "response": text}
