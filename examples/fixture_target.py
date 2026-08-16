#!/usr/bin/env python3
"""A local stand-in for a government chat system, so the recording loop can be
run end to end with nothing installed and nothing reachable.

It answers on `POST /chat` with the responses committed in the demo bundle,
looked up by the `trace_id` the example adapter sends. That makes it a fixture,
not a model: it exists so you can watch `plumbline record` talk to something
real over a real socket, and then grade what came back with the same audit
command as any other bundle.

    python3 examples/fixture_target.py &
    PYTHONPATH=src python3 -m plumbline record --config examples/riverbend-live.toml --synthetic
    PYTHONPATH=src python3 -m plumbline audit  --config examples/riverbend-live.toml

`--fabricate` runs the same fixture with one policy number changed in English
only, which is the tamper drill arriving through the live path: the recording
is legitimate, sealed, and untampered, and the cross-language suite still
catches the number that disagrees with its Spanish twin.

Standard library only. Binds to the loopback interface.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent.parent / "datasets" / "riverbend-demo"
FABRICATED = ("850", "900")  # the monthly cap, misremembered


def load_answers(fabricate: bool) -> dict[str, str]:
    items = {}
    for line in (BUNDLE / "items.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            items[item["id"]] = item
    answers = {}
    for line in (BUNDLE / "responses.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        text = entry["response"]
        if fabricate and items.get(entry["id"], {}).get("lang") == "en":
            text = text.replace(*FABRICATED)
        answers[entry["id"]] = text
    return answers


def make_handler(answers: dict[str, str]):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self.reply(400, {"error": "body was not JSON"})
            if self.path != "/chat":
                return self.reply(404, {"error": f"no route {self.path}"})
            trace_id = body.get("trace_id")
            if trace_id not in answers:
                return self.reply(
                    404, {"error": f"this fixture has no canned answer for "
                                   f"{trace_id!r}"})
            self.reply(200, {"reply": answers[trace_id]})

        def reply(self, status: int, payload: dict):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            print(f"fixture-target: {fmt % args}")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--fabricate", action="store_true",
                        help="change one policy number in the English answers "
                             "only, so the recorded bundle fails the way a "
                             "real fabrication would")
    args = parser.parse_args()
    answers = load_answers(args.fabricate)
    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 make_handler(answers))
    mode = "FABRICATING" if args.fabricate else "faithful"
    print(f"fixture target ({mode}) on http://127.0.0.1:{args.port}/chat — "
          f"{len(answers)} canned answers; Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nfixture target stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
