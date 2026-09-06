"""A push to `main` must not cancel the verdict on the commit before it.

GitHub cancels an in-progress run when a new run enters the same `concurrency`
group and the group sets `cancel-in-progress: true`. Keyed on `github.ref`
alone, every commit pushed to `main` enters the same group -- so a second push
cancels the run that was checking the first one.

The consequence is not a red build. A cancelled run has conclusion
`cancelled`, which is neither success nor failure: no check goes red, no
notification is sent, and the commit stays on `main` having been examined by
nothing. Measured across this portfolio, a ref-only key silently voided about a
third of one repository's main-branch runs.

A pull request is the case the setting was written for -- a force-push really
does supersede its predecessor -- so pull requests keep one group per PR and
branch pushes get one group per commit.

Read as text, for the same reason `test_ci_parity.py` gives: this project has
no third-party dependencies and a YAML parser for four files would cost more
than it buys. The floor test below is what keeps the text scan from passing
over nothing.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"

# The interpolation that separates commits on a branch push while collapsing a
# pull request's pushes into one group. Any expression naming the SHA would do;
# requiring this one keeps the four workflows saying it the same way.
PER_COMMIT = "github.event_name == 'pull_request' && 'pr' || github.sha"

_TOP_LEVEL_KEY = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):", re.M)


def _top_level_block(text: str, key: str) -> str | None:
    """The lines under a top-level `key:` mapping, or None if there is no such key."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _TOP_LEVEL_KEY.match(line)
        if match is None or match.group("key") != key:
            continue
        body: list[str] = []
        for candidate in lines[i + 1:]:
            if candidate.strip() and not candidate.startswith((" ", "\t")):
                break
            body.append(candidate)
        return "\n".join(body)
    return None


def _pushes_to_a_branch(text: str) -> bool:
    """Whether the workflow triggers on a push to a branch rather than only a tag."""
    triggers = _top_level_block(text, "on")
    if triggers is None:
        return False
    push = re.search(r"^  push:\n((?:    .*\n?)*)", triggers + "\n", re.M)
    return push is not None and "branches:" in push.group(1)


def _concurrency(text: str) -> tuple[str, str] | None:
    """(group, cancel-in-progress) for the workflow, or None if it declares neither."""
    block = _top_level_block(text, "concurrency")
    if block is None:
        return None
    group = re.search(r"^\s*group:\s*(.+)$", block, re.M)
    cancel = re.search(r"^\s*cancel-in-progress:\s*(\S+)", block, re.M)
    if group is None:
        return None
    return group.group(1).strip(), (cancel.group(1) if cancel else "false")


def _workflows() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


class ACommitOnMainAlwaysGetsAVerdict(unittest.TestCase):
    def test_the_scan_reads_the_workflows_that_gate_main(self):
        """A floor. A scan that finds no workflow, or no workflow that pushes to
        a branch, passes every assertion below over nothing -- which is the exact
        shape of the bug this file exists to catch elsewhere."""
        files = _workflows()
        self.assertGreaterEqual(len(files), 5, [f.name for f in files])
        pushing = {f.name for f in files
                   if _pushes_to_a_branch(f.read_text(encoding="utf-8"))}
        self.assertLessEqual(
            {"tests.yml", "security.yml", "scorecard.yml", "pages.yml"}, pushing,
            f"the branch-push scan found {sorted(pushing)}")

    def test_no_branch_push_shares_a_cancelling_group_with_another_commit(self):
        offenders: list[str] = []
        for path in _workflows():
            text = path.read_text(encoding="utf-8")
            declared = _concurrency(text)
            if declared is None or not _pushes_to_a_branch(text):
                continue
            group, cancel = declared
            if cancel == "false":
                # Queues rather than cancels; the first commit's run still finishes.
                continue
            if "github.sha" not in group:
                offenders.append(f"{path.name}: group: {group}")
        self.assertEqual(
            offenders, [],
            "these workflows run on a branch push and cancel in-progress runs in "
            "their group, but the group does not name the commit -- so a second "
            "push to `main` cancels the first commit's only verdict: "
            f"{offenders}. Append -${{{{ {PER_COMMIT} }}}} to the group.")

    def test_the_three_that_carried_the_ref_only_key_now_name_the_commit(self):
        """The scan above answers "nothing is wrong". This answers "these three
        were wrong and were fixed", so removing one from the scan's reach fails
        here rather than passing there."""
        for name in ("tests.yml", "security.yml", "scorecard.yml"):
            declared = _concurrency((WORKFLOWS / name).read_text(encoding="utf-8"))
            self.assertIsNotNone(declared, name)
            assert declared is not None
            self.assertIn(PER_COMMIT, declared[0], name)


if __name__ == "__main__":
    unittest.main()
