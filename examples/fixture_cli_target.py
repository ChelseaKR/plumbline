#!/usr/bin/env python3
"""A local command-line stand-in for a government chat system.

The HTTP fixture next door exists so `plumbline record` can be watched talking
to something over a real socket. This one exists for the other half: a target
that is a **program**, recorded with no network involved at all, which is what
the offline-first default actually looks like.

It reads one JSON object on stdin, prints one JSON object on stdout, and
answers from the responses committed in the demo bundle:

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabricate", action="store_true")
    parser.add_argument("--hang", action="store_true")
    parser.add_argument("--flood", action="store_true")
    parser.add_argument("--fail", action="store_true")
    parser.add_argument("--silent", action="store_true")
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

    raw = sys.stdin.read()
    try:
        request = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        print(f"navigator: stdin was not JSON: {e}", file=sys.stderr)
        return 2

    answers = load_answers(args.fabricate)
    trace_id = request.get("trace_id")
    if trace_id not in answers:
        print(f"navigator: no canned answer for {trace_id!r}", file=sys.stderr)
        return 4
    json.dump({"reply": {"text": answers[trace_id]}}, sys.stdout,
              ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
