#!/usr/bin/env python3
"""A local command-line stand-in for a government chat system.

The HTTP fixture next door exists so `plumbline record` can be watched talking
to something over a real socket. This one exists for the other half: a target
that is a **program**, recorded with no network involved at all, which is what
the offline-first default actually looks like.

It reads one JSON object **per line** on stdin, prints one JSON object per
line on stdout, and answers from the responses committed in the demo bundle.
One line in and one line out is the single-turn case; a multi-turn item is
`[adapter.conversation] mode = "lines"`, which writes one line per turn to the
same process and expects one answer line back per turn.

    echo '{"trace_id": "rent-cap-en-formal"}' | python3 examples/fixture_cli_target.py

    PYTHONPATH=src python3 -m plumbline record --config examples/riverbend-cli.toml --synthetic
    PYTHONPATH=src python3 -m plumbline audit  --config examples/riverbend-cli.toml

Flags that make it misbehave on purpose, so the adapter's bounds can be seen
refusing rather than described:

    --fabricate   change one policy number in the English answers only
    --hang        never exit, so the timeout has something to kill
    --flood       print far more than any sane output ceiling
    --fail        exit non-zero, so a broken integration cannot read as a
                  merely mediocre target
    --silent      exit 0 having printed nothing
    --comply-late on a multi-turn item, give way on turn 2 and refuse again
                  on the last turn, so the leak is invisible to every suite
                  that reads only the final response

Standard library only. Opens no socket.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent.parent / "datasets" / "riverbend-demo"
FABRICATED = ("850", "900")  # the monthly cap, misremembered

# Fixture copy, not bundle data — see the note in `fixture_target.py`.
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


def turn_answer(item: dict, final: str, turn: int, comply_late: bool) -> str:
    """This fixture's answer to one turn. Mirrors `fixture_target.py`.

    The compliance lands on turn 2 and the last turn refuses cleanly, so the
    leak is invisible to every suite that reads only the final response. The
    leaked string is the item's own first `forbidden` entry.
    """
    if turn == 1:
        return OPENER.get(item.get("lang", "en"), OPENER["en"])
    if comply_late and turn == 2:
        forbidden = (item.get("forbidden") or ["system prompt"])[0]
        return (f"Fine, just this once: {forbidden}. "
                f"Do not tell anyone I said that.")
    return final


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabricate", action="store_true")
    parser.add_argument("--hang", action="store_true")
    parser.add_argument("--flood", action="store_true")
    parser.add_argument("--fail", action="store_true")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--comply-late", action="store_true")
    args = parser.parse_args()

    if args.hang:
        while True:
            time.sleep(3600)
    if args.flood:
        chunk = "x" * 65536
        for _ in range(256):
            sys.stdout.write(chunk)
        sys.stdout.flush()
        return 0
    if args.fail:
        print("navigator: the policy corpus could not be opened",
              file=sys.stderr)
        return 3
    if args.silent:
        return 0

    answers = load_answers(args.fabricate)
    items = load_items()

    # One request per line, one reply per line: a single-turn recording writes
    # exactly one line and this loop runs once, which is why the single-turn
    # invocation at the top of this docstring still works unchanged. A
    # multi-turn recording writes one line per turn to the same process, so
    # the turn counter lives here rather than in any session state.
    turn = 0
    for raw in sys.stdin:
        if not raw.strip():
            continue
        turn += 1
        try:
            request = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"navigator: stdin line {turn} was not JSON: {e}",
                  file=sys.stderr)
            return 2
        trace_id = request.get("trace_id")
        if trace_id not in answers:
            print(f"navigator: no canned answer for {trace_id!r}",
                  file=sys.stderr)
            return 4
        item = items.get(trace_id, {})
        if turn == 1 and not item.get("turns"):
            text = answers[trace_id]
        else:
            text = turn_answer(item, answers[trace_id], turn, args.comply_late)
        json.dump({"reply": {"text": text}}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        sys.stdout.flush()
    if turn == 0:
        print("navigator: stdin held no request", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
