"""The ideas page must be held to the tree, in both directions.

`docs/feature-expansion-ideas.md` opened with "None of this is implemented,
scheduled, or promised" for twenty-two days after all six of its proposals
shipped in `v0.2.0`. Nothing read that sentence, so nothing could contradict
it. `tools/check_expansion_status.py` is what reads it now.

This file checks the same two things `tests/test_claims.py` checks about the
published figures: that the declarations hold today, and that each way they
could stop holding actually goes red. The second half is the point. A gate
over a status field has an obvious happy path and two distinct failure modes,
and only one of them has ever happened here -- a proposal published as open
while its module sits in the tree -- so that is the one most worth proving can
fail.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_expansion_status as status  # noqa: E402

OPEN = status.OPEN
SHIPPED = status.SHIPPED


def _page(entries, *, total=None, shipped=None, opened=None) -> str:
    """A synthetic page in the shape the checker reads.

    Synthetic rather than the real document for every failure case, so the
    planted defect is the only thing wrong and a test cannot pass because
    something else in the page happened to be broken too.
    """
    built = [e for e in entries if e[2] == SHIPPED]
    unbuilt = [e for e in entries if e[2] == OPEN]
    head = (
        "# Feature expansion ideas\n\nThis page holds "
        f"{total or status.WORDS[len(entries)]} proposals for work beyond "
        f"M9: {shipped or status.WORDS[len(built)]} have shipped and "
        f"{opened or status.WORDS[len(unbuilt)]} are open.\n")
    body = ""
    for number, title, state, paths in entries:
        named = ", ".join(f"`{p}`" for p in paths) or "nothing in particular"
        body += (f"\n## {number}. {title}\n\n**Status: {state}** — {named}.\n"
                 f"\n**The idea:** a sentence so the section has a body.\n")
    return head + body


def _proposal(number, title, state, paths) -> status.Proposal:
    return status.Proposal(number=number, heading=f"{number}. {title}",
                           status=state, paths=tuple(paths))


class ThePageMatchesTheTree(unittest.TestCase):
    def test_every_declaration_holds(self):
        self.assertEqual(
            status.check(), [],
            "the ideas page and the tree disagree; run "
            "`python3 tools/check_expansion_status.py` for the list")

    def test_the_check_command_agrees(self):
        self.assertEqual(status.main([]), 0)

    def test_the_shipped_universe_passes_every_refusal(self):
        status.refuse_a_universe_that_cannot_fail()

    def test_the_declared_paths_are_read_from_the_tree_not_asserted_here(self):
        # The figures this gate rests on are file-existence facts. Read them
        # directly, so a checker that stopped looking at the filesystem would
        # not be able to satisfy this file by agreeing with itself.
        for proposal in status.PROPOSALS:
            for path in proposal.paths:
                exists = (REPO / path).exists()
                self.assertEqual(
                    exists, proposal.status == SHIPPED,
                    f"proposal {proposal.number} is declared "
                    f"{proposal.status!r} and {path} "
                    f"{'exists' if exists else 'does not exist'}")

    def test_the_command_prints_what_it_examined(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(status.main([]), 0)
        printed = out.getvalue()
        total, shipped, paths = status.census()
        self.assertIn(f"{shipped} of {total} proposals", printed)
        self.assertIn(f"{paths} declared path(s)", printed)

    def test_both_statuses_are_actually_in_use(self):
        # The reason the refusal below exists, asserted against the shipped
        # set: a page where everything shipped exercises one direction of the
        # existence check and reports clean about the other.
        self.assertEqual({p.status for p in status.PROPOSALS},
                         set(status.STATUSES))


class TheCheckCanFail(unittest.TestCase):
    """Every failure mode, proved rather than assumed."""

    def test_a_proposal_published_as_open_whose_module_exists_is_caught(self):
        # The defect that actually happened, one proposal at a time: somebody
        # builds it and the page goes on saying nobody has.
        entries = [(7, "A thing somebody built", OPEN, ["README.md"])]
        problems = status.check(
            (_proposal(*entries[0]),), _page(entries))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("published as open and README.md exists", problems[0])

    def test_a_proposal_published_as_shipped_whose_module_is_gone_is_caught(self):
        entries = [(1, "A thing nobody built", SHIPPED,
                    ["src/plumbline/nothing_here.py"])]
        problems = status.check(
            (_proposal(*entries[0]),), _page(entries))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("published as shipped", problems[0])
        self.assertIn("is not in the tree", problems[0])

    def test_a_section_that_no_longer_exists_is_caught(self):
        entries = [(1, "A heading that is there", SHIPPED, ["README.md"])]
        renamed = _proposal(1, "A heading nobody has written", SHIPPED,
                            ["README.md"])
        problems = status.check((renamed,), _page(entries))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("no section headed", problems[0])

    def test_a_heading_written_twice_is_caught(self):
        entries = [(1, "Said twice", SHIPPED, ["README.md"]),
                   (1, "Said twice", SHIPPED, ["README.md"])]
        # One declaration, so the summary counts are the declaration's: the
        # duplicate heading has to be the only thing this case plants.
        problems = status.check(
            (_proposal(*entries[0]),),
            _page(entries, total="one", shipped="one", opened="zero"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("appears 2 times", problems[0])

    def test_a_status_line_that_disagrees_with_the_declaration_is_caught(self):
        entries = [(1, "Built, and the page says otherwise", OPEN,
                    ["src/plumbline/nothing_here.py"])]
        declared = _proposal(1, "Built, and the page says otherwise", SHIPPED,
                             ["src/plumbline/nothing_here.py"])
        problems = status.check(
            (declared,), _page(entries, shipped="one", opened="zero"))
        # Two, and both are real: the page and the declaration disagree, and
        # the tree says the declaration is the wrong one.
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("reads `**Status: open**`", problems[0])

    def test_a_status_the_section_never_states_is_caught(self):
        page = ("# Feature expansion ideas\n\nThis page holds one proposals "
                "for work beyond M9: one have shipped and zero are open.\n"
                "\n## 1. No status line at all\n\n`README.md` and nothing "
                "saying what became of it.\n")
        problems = status.check(
            (_proposal(1, "No status line at all", SHIPPED, ["README.md"]),),
            page)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("states its status 0 times", problems[0])

    def test_a_path_the_section_never_names_is_caught(self):
        # The subtler one: the status is right, the tree agrees, and a reader
        # has no way to check either because the page points at nothing.
        entries = [(1, "Silent about its evidence", SHIPPED, [])]
        declared = _proposal(1, "Silent about its evidence", SHIPPED,
                             ["README.md"])
        problems = status.check((declared,), _page(entries))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("never names `README.md`", problems[0])

    def test_a_summary_sentence_that_disagrees_is_caught(self):
        entries = [(1, "One shipped thing", SHIPPED, ["README.md"])]
        problems = status.check(
            (_proposal(*entries[0]),), _page(entries, shipped="seven"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("shipped is 'seven'", problems[0])

    def test_a_summary_sentence_that_is_gone_is_caught(self):
        page = ("# Feature expansion ideas\n\nSome proposals.\n"
                "\n## 1. A thing\n\n**Status: shipped** — `README.md`.\n")
        problems = status.check(
            (_proposal(1, "A thing", SHIPPED, ["README.md"]),), page)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("stated 0 times", problems[0])


class TheUniverseCannotShrinkInSilence(unittest.TestCase):
    """Five floors, each proved to refuse. None of them is a counter."""

    def test_a_proposal_with_no_declared_path_is_refused(self):
        entries = [(1, "Bound to nothing", SHIPPED, [])]
        with self.assertRaises(status.Stale) as caught:
            status.refuse_a_universe_that_cannot_fail(
                (_proposal(1, "Bound to nothing", SHIPPED, []),),
                _page(entries))
        self.assertIn("declares no path", str(caught.exception))

    def test_a_status_this_file_does_not_understand_is_refused(self):
        entries = [(1, "Half done", SHIPPED, ["README.md"])]
        with self.assertRaises(status.Stale) as caught:
            status.refuse_a_universe_that_cannot_fail(
                (_proposal(1, "Half done", "sort of", ["README.md"]),),
                _page(entries))
        self.assertIn("not one of", str(caught.exception))

    def test_a_path_declared_by_two_proposals_is_refused(self):
        entries = [(1, "First", SHIPPED, ["README.md"]),
                   (2, "Second", SHIPPED, ["README.md"])]
        with self.assertRaises(status.Stale) as caught:
            status.refuse_a_universe_that_cannot_fail(
                tuple(_proposal(*e) for e in entries), _page(entries))
        self.assertIn("resting on the other's evidence", str(caught.exception))

    def test_a_numbered_proposal_nobody_declared_is_refused(self):
        # A tenth idea added to the page with no entry here would be prose
        # nothing reads, which is the state the whole page was in.
        entries = [(1, "Declared", SHIPPED, ["README.md"]),
                   (2, "Nobody declared this one", OPEN, ["nothing.txt"])]
        with self.assertRaises(status.Stale) as caught:
            status.refuse_a_universe_that_cannot_fail(
                (_proposal(*entries[0]),), _page(entries))
        self.assertIn("Nobody declared this one", str(caught.exception))

    def test_a_page_where_everything_shipped_is_refused(self):
        entries = [(1, "First", SHIPPED, ["README.md"]),
                   (2, "Second", SHIPPED, ["DESIGN.md"])]
        with self.assertRaises(status.Stale) as caught:
            status.refuse_a_universe_that_cannot_fail(
                tuple(_proposal(*e) for e in entries), _page(entries))
        self.assertIn("only one direction", str(caught.exception))

    def test_the_refusals_do_not_fire_on_a_healthy_synthetic_page(self):
        # The floors have to be floors, not a second way for a correct page to
        # fail: a mixed, well-formed universe passes all five.
        entries = [(1, "Built", SHIPPED, ["README.md"]),
                   (2, "Not built", OPEN, ["nothing-here.txt"])]
        status.refuse_a_universe_that_cannot_fail(
            tuple(_proposal(*e) for e in entries), _page(entries))


if __name__ == "__main__":
    unittest.main()
