"""The repository's own gate workflow and the Makefile must be the same gate.

`.github/workflows/tests.yml` is where this project checks itself, and its
header says every step "has to be able to fail. A step that cannot go red is a
badge, and this repository exists to argue against those." A step that can only
run in CI is a nearer relative of a badge than it looks: nobody can run it, so
nobody finds out it stopped meaning anything until the day it fires.

Until 2026-08-28 three of that workflow's steps were inline script with no
target behind them -- the byte-for-byte reproduction of the committed audit, the
re-check of the committed report against its own seal, and the tamper drill. The
Makefile said so and gave a reason: both mutate the working tree, and a gate
people learn to run `git checkout --` after is a gate people learn to ignore.
The reason was sound and the consequence was still that `make verify` passed on
trees this workflow rejects. Neither check needs to mutate anything, so now
neither does, and both are in `verify`.

What is checked here: every `run:` step in tests.yml is a `make` target, that
target exists, and `verify` reaches it.

Scope. `tests.yml` is the repository's gate and is held to this.
`security.yml` is not, and the exemption is a tooling fact rather than a
preference: its semgrep step runs inside a pinned semgrep container and its
secret scan is a pinned marketplace action, so neither is a shell command a
Makefile could run identically. `make sast` is a local approximation of the
first and says so. `release.yml`, `publish-pypi.yml`, `pages.yml` and
`scorecard.yml` publish or report rather than gate a merge.

tests.yml is read as text: this project has no third-party dependencies, and
adding a YAML parser to check one file would cost more than it buys.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "tests.yml"
MAKEFILE = REPO / "Makefile"

# Anything that is not `run: <one line>` -- notably `run: |`, which opens an
# inline script -- is caught rather than skipped, because an inline script is
# precisely the thing that has no target behind it.
RUN_STEP = re.compile(r"^\s*(?:-\s+)?run:\s*(.*)$", re.M)
MAKE_CALL = re.compile(r"^make\s+([a-z][a-z0-9-]*)$")

# `uv sync --locked` installs the tooling the quality job's `make verify` needs.
# It is setup, not a gate: it cannot report a finding about this repository's
# own code, only that the lockfile and the manifest disagree.
ALLOWED_NON_MAKE = {"uv sync --locked"}


def _run_commands() -> list[str]:
    return [m.group(1).strip()
            for m in RUN_STEP.finditer(WORKFLOW.read_text(encoding="utf-8"))]


def _rules() -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([a-z][a-z0-9-]*)\s*:(?!=)(.*)$", line)
        if match:
            rules[match.group(1)] = match.group(2).split()
    return rules


def _reachable(target: str) -> set[str]:
    rules = _rules()
    seen: set[str] = set()
    stack = [target]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(rules.get(current, []))
    return seen


def _called() -> set[str]:
    return {m.group(1) for c in _run_commands() if (m := MAKE_CALL.match(c))}


class TheWorkflowAndTheMakefileAreOneGate(unittest.TestCase):
    def test_both_files_were_actually_read(self):
        """A floor. A renamed workflow would pass every check below over
        nothing, which is the failure this whole file is about."""
        self.assertTrue(WORKFLOW.is_file(), WORKFLOW)
        self.assertTrue(MAKEFILE.is_file(), MAKEFILE)
        self.assertGreaterEqual(len(_run_commands()), 4, _run_commands())
        self.assertIn("verify", _rules())

    def test_every_step_is_a_make_target(self):
        offenders = [c for c in _run_commands()
                     if not MAKE_CALL.match(c) and c not in ALLOWED_NON_MAKE]
        self.assertEqual(
            offenders, [],
            "every step in tests.yml must be `make <target>` so the local gate "
            f"can run it; these are not: {offenders}")

    def test_every_target_it_calls_exists(self):
        called = _called()
        self.assertTrue(called, "no make target found in tests.yml")
        missing = sorted(called - set(_rules()))
        self.assertEqual(missing, [], missing)

    def test_verify_reaches_every_target_the_workflow_calls(self):
        """`make verify` green must mean this workflow green."""
        # test-bare is the matrix job's bare-interpreter run of the same suite
        # `verify` covers through `test`, which adds the coverage floor on top.
        called = _called() - {"test-bare"}
        uncovered = sorted(called - _reachable("verify"))
        self.assertEqual(
            uncovered, [],
            "the workflow runs these and `make verify` does not reach them, so "
            f"the local gate can be green on a tree CI rejects: {uncovered}")

    def test_verify_still_reaches_the_gates_that_used_to_be_ci_only(self):
        covered = _reachable("verify")
        for target in ("reproduce", "tamper-drill", "lint", "test", "site-check"):
            self.assertIn(target, covered, target)


if __name__ == "__main__":
    unittest.main()
