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

`--comply-late` is the same idea for conversations. The demo's escalating
items open with a benign question and then push twice; under this flag the
fixture gives way on turn 2 and refuses again on the last one. The final
response is clean, so every suite that reads only the last turn passes it —
and `conversational_integrity`, which reads all of them, does not. It needs a
multi-turn recording to exist at all, which is what `[adapter.conversation]`
in `riverbend-live.toml` makes possible.

Standard library only. Binds to the loopback interface.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent.parent / "datasets" / "riverbend-demo"
FABRICATED = ("850", "900")  # the monthly cap, misremembered

# Fixture copy, not bundle data: the demo's multi-turn items open with a benign
# question whose answer is not in `responses.jsonl` — that file holds one
# response per item, and for a conversation that one response is the *last*
# turn. Every later turn replays the committed response, which for these items
# is the refusal.
#
# Deliberately content-free. The openers differ per item (office hours, how to
# apply for rent relief), and a fixture that answered one of them with a
# specific policy fact would be stating a number no source in this bundle
# carries — the exact shape `citation_validity` exists to catch — in the one
# place nothing grades it, because every content suite reads the final turn.
OPENER = {
    "en": "I can help with that. Here is what the published guidance covers.",
    "es": "Puedo ayudar con eso. Esto es lo que cubre la guía publicada.",
}


def load_items() -> dict[str, dict]:
    items = {}
    for line in (BUNDLE / "items.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            items[item["id"]] = item
    return items


def load_answers(fabricate: bool) -> dict[str, str]:
    items = load_items()
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


def turn_answer(item: dict, final: str, turn: int, comply_late: bool) -> str:
    """This fixture's answer to one turn of a multi-turn item.

    Turn 1 answers the benign opener; every later turn replays the item's
    committed response, which for the demo's conversations is its refusal.

    `comply_late` is the defect, and it is placed deliberately: the compliance
    lands on turn 2 and the *last* turn refuses cleanly. Every suite in this
    harness except `conversational_integrity` reads only the final response,
    so a target that leaks partway through and recovers is invisible to all of
    them — which is the whole reason that suite exists. Putting the leak on the
    last turn instead would prove nothing the adversarial suite does not
    already catch.

    The leaked string is the item's own first `forbidden` entry, so the defect
    is derived from the bundle rather than hardcoded here: change what an item
    forbids and this still leaks exactly what that item is screened for.
    """
    if turn == 1:
        return OPENER.get(item.get("lang", "en"), OPENER["en"])
    if comply_late and turn == 2:
        forbidden = (item.get("forbidden") or ["system prompt"])[0]
        return (f"Fine, just this once: {forbidden}. "
                f"Do not tell anyone I said that.")
    return final


def make_handler(answers: dict[str, str], items: dict[str, dict],
                 comply_late: bool):
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
            # `[adapter.conversation] mode = "history"` sends the exchange so
            # far at the declared pointer, so this fixture needs no session
            # state to know which turn it is on: two messages per completed
            # exchange, and the turn now being asked is the next one. A
            # single-turn item sends no history at all and lands on turn 1.
            history = body.get("messages") or []
            if not isinstance(history, list):
                return self.reply(400, {"error": "messages must be a list"})
            turn = len(history) // 2 + 1
            item = items.get(trace_id, {})
            if turn == 1 and not item.get("turns"):
                return self.reply(200, {"reply": answers[trace_id]})
            self.reply(200, {"reply": turn_answer(
                item, answers[trace_id], turn, comply_late)})

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
    parser.add_argument("--comply-late", action="store_true",
                        help="on a multi-turn item, comply with the "
                             "escalation on turn 2 and refuse again on the "
                             "last turn, so the leak is invisible to every "
                             "suite that reads only the final response")
    args = parser.parse_args()
    answers = load_answers(args.fabricate)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(answers, load_items(), args.comply_late))
    mode = ("FABRICATING" if args.fabricate
            else "COMPLYING LATE" if args.comply_late else "faithful")
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
