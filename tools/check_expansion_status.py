#!/usr/bin/env python3
"""Hold `docs/feature-expansion-ideas.md` to what is actually in the tree.

The page opened, for two hundred and forty-odd commits, with this sentence:

    None of this is implemented, scheduled, or promised -- it is ideation,
    dated and attributed like everything else here, so a reader can tell a
    considered-but-not-built idea from a considered-and-built one.

All six of its proposals had shipped by then: `signing.py`, `sarif.py`,
`retention.py`, `history.py`, the `conversational_integrity` suite, and the
SBOM/Scorecard/signed-release workflows. The sentence was a claim about the
system with nothing holding it to being true, which is the defect this
repository exists to argue against, in the document that argues it. Correcting
the prose without leaving anything behind it would only have reset the clock.

So this is the thing behind it, built the way `tools/check_claims.py` is: a
declared universe, a structural refusal for every way the check could report
green over a surface it never looked at, and a failure mode in both
directions.

Each proposal below declares the paths that would make it real. A proposal
declared `shipped` whose paths are not in the tree is a failure; a proposal
declared `open` whose paths ARE in the tree is the failure that actually
happened, and it is the one this file exists for -- the next person who
implements idea 7 cannot leave the page saying nobody has.

    python3 tools/check_expansion_status.py

Exit 0 when every declaration matches the tree and the page, 1 otherwise. No
network, no clock, no randomness: the result is a pure function of the
repository, the same property the reports themselves have.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: The one document this file governs. Named once, here, so a moved page is a
#: read error rather than a silently empty scan.
DOC = "docs/feature-expansion-ideas.md"

SHIPPED = "shipped"
OPEN = "open"
STATUSES = (SHIPPED, OPEN)

WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten", "eleven", "twelve")


class Stale(Exception):
    """The page and the tree disagree about what has been built."""


def _spell(n: int) -> str:
    if not 0 <= n < len(WORDS):
        raise Stale(f"no spelling for {n}; the summary sentence needs "
                    f"rewriting by hand")
    return WORDS[n]


@dataclass(frozen=True)
class Proposal:
    """One numbered proposal, and the evidence that decides its status.

    `paths` are repository-relative and are the paths that came into existence
    *with* the feature. A path that was already there before the proposal was
    written proves nothing about it and must not be listed: it would make this
    entry pass whatever happened, which is the vacuous pass wearing a status
    field.
    """

    number: int
    heading: str
    status: str
    paths: tuple[str, ...]


PROPOSALS: tuple[Proposal, ...] = (
    Proposal(
        number=1,
        heading="1. Detached report signatures",
        status=SHIPPED,
        paths=("src/plumbline/signing.py",
               "docs/adr/0002-shared-secret-report-signatures.md"),
    ),
    Proposal(
        number=2,
        heading="2. Multi-turn conversation items",
        status=SHIPPED,
        paths=("src/plumbline/suites/conversational_integrity.py",
               "docs/adr/0003-multi-turn-items-are-additive-not-a-new-bundle-format.md"),
    ),
    Proposal(
        number=3,
        heading="3. Machine-readable findings for consuming PRs",
        status=SHIPPED,
        paths=("src/plumbline/sarif.py",),
    ),
    Proposal(
        number=4,
        heading="4. Supply-chain closure: SBOM, Scorecard, signed release",
        status=SHIPPED,
        paths=("sbom.cdx.json", "tools/build_sbom.py",
               ".github/workflows/release.yml",
               ".github/workflows/scorecard.yml",
               ".github/workflows/publish-pypi.yml"),
    ),
    Proposal(
        number=5,
        heading="5. Recording retention and redaction lifecycle",
        status=SHIPPED,
        paths=("src/plumbline/retention.py", "docs/recordings-data-card.md"),
    ),
    Proposal(
        number=6,
        heading="6. Longitudinal run history, not just one stored baseline",
        status=SHIPPED,
        paths=("src/plumbline/history.py",
               "docs/adr/0001-longitudinal-history-is-observation-not-inference.md"),
    ),
    Proposal(
        number=7,
        heading="7. A committed required-checks contract",
        status=OPEN,
        paths=(".github/required-checks.json",
               "tools/check_required_checks.py"),
    ),
    Proposal(
        number=8,
        heading="8. A human-adjudicated sample for the model judge",
        status=OPEN,
        paths=("datasets/judge-agreement/", "tools/judge_agreement.py"),
    ),
    Proposal(
        number=9,
        heading="9. A staleness gate for the two documents nothing holds",
        status=OPEN,
        paths=("tools/check_ledger_freshness.py",),
    ),
)


#: The page's own count of itself. Bound here for the same reason
#: `check_claims.py` binds a figure rather than trusting a sentence: a
#: summary line that nothing recomputes is the first thing to go stale, and
#: this page has already been stale in exactly that way once.
SUMMARY = re.compile(
    r"(?P<total>[a-z]+) proposals for work beyond M9: (?P<shipped>[a-z]+) "
    r"have shipped and (?P<open>[a-z]+) are open")

#: A numbered proposal heading. Matched line-anchored so a number in prose is
#: not mistaken for a section.
HEADING = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)

#: The per-proposal status, stated once in the section it is about. One
#: spelling, in one place: a status restated in a summary table as well would
#: be a second copy for the first one to drift away from.
STATUS_LINE = re.compile(r"\*\*Status:\s+(" + "|".join(STATUSES) + r")\*\*")


def _raw(doc: str = DOC) -> str:
    return (REPO / doc).read_text(encoding="utf-8")


def sections(text: str | None = None) -> list[tuple[str, str]]:
    """The numbered proposal sections, as (heading, body) in document order.

    A list rather than a dict: a heading written twice has to be reportable,
    and a dict would silently keep one of them.
    """
    if text is None:
        text = _raw()
    found = list(HEADING.finditer(text))
    out: list[tuple[str, str]] = []
    for i, match in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        out.append((f"{match.group(1)}. {match.group(2)}",
                    text[match.end():end]))
    return out


def refuse_a_universe_that_cannot_fail(
    proposals: tuple[Proposal, ...] = PROPOSALS,
    text: str | None = None,
) -> None:
    """The floor. Each refusal names a way this file could report green over
    something it never examined. None of them is a counter, so none of them
    becomes a hand-maintained number that jams a queue.
    """
    if text is None:
        text = _raw()

    for proposal in proposals:
        if proposal.status not in STATUSES:
            raise Stale(
                f"proposal {proposal.number} declares status "
                f"{proposal.status!r}, which is not one of {list(STATUSES)}; "
                f"a status this file does not understand is checked by "
                f"nothing")
        if not proposal.paths:
            raise Stale(
                f"proposal {proposal.number} ({proposal.heading!r}) declares "
                f"no path, so nothing in the tree decides its status and it "
                f"would hold whatever the page said")

    owner: dict[str, int] = {}
    for proposal in proposals:
        for path in proposal.paths:
            if path in owner:
                raise Stale(
                    f"{path!r} is declared by proposal {owner[path]} and by "
                    f"proposal {proposal.number}; one of the two would be "
                    f"resting on the other's evidence")
            owner[path] = proposal.number

    declared = {p.heading for p in proposals}
    present = {heading for heading, _ in sections(text)}
    undeclared = sorted(present - declared)
    if undeclared:
        raise Stale(
            f"{undeclared} are numbered proposals in {DOC} that this file does "
            f"not declare, so nothing holds their status to the tree. Add a "
            f"Proposal for each, or stop numbering them")

    statuses = {p.status for p in proposals}
    if len(statuses) < 2:
        raise Stale(
            f"every declared proposal is {statuses.pop()!r}, so only one "
            f"direction of the existence check is ever exercised against this "
            f"tree. A page where everything shipped needs the next open idea "
            f"written down before this gate means anything again")


def check(
    proposals: tuple[Proposal, ...] = PROPOSALS,
    text: str | None = None,
) -> list[str]:
    """One line per declaration the page or the tree does not bear out."""
    if text is None:
        text = _raw()
    # The refusals are about the *shipped* universe. Tests hand this function
    # one deliberately broken proposal at a time to prove each failure mode,
    # and "every proposal here is shipped" is true of most such calls and
    # means nothing about the repository -- the same `is PROPOSALS`
    # distinction `check_claims.check` draws.
    if proposals is PROPOSALS:
        refuse_a_universe_that_cannot_fail(proposals, text)

    found = sections(text)
    seen = Counter(heading for heading, _ in found)
    bodies: dict[str, str] = {}
    for heading, body in found:
        bodies.setdefault(heading, body)

    problems: list[str] = []
    for proposal in proposals:
        problems.extend(_proposal_problems(proposal, seen, bodies))
    problems.extend(_summary_problems(proposals, text))
    return problems


def _proposal_problems(
    proposal: Proposal,
    seen: Counter[str],
    bodies: dict[str, str],
) -> list[str]:
    """Everything wrong with one proposal's section, or an empty list."""
    count = seen.get(proposal.heading, 0)
    if count == 0:
        return [f"{DOC}: there is no section headed {proposal.heading!r} any "
                f"more, so nothing on the page carries the status this file "
                f"checks. If it was renamed on purpose, rename it here too"]
    if count > 1:
        return [f"{DOC}: {proposal.heading!r} appears {count} times; this file "
                f"would check one of them and leave the rest to drift"]

    body = bodies[proposal.heading]
    stated = STATUS_LINE.findall(body)
    if len(stated) != 1:
        return [f"{DOC}: proposal {proposal.number} states its status "
                f"{len(stated)} times; it must say `**Status: "
                f"{proposal.status}**` exactly once, in its own section"]

    problems: list[str] = []
    if stated[0] != proposal.status:
        problems.append(
            f"{DOC}: proposal {proposal.number} reads "
            f"`**Status: {stated[0]}**` and this file declares "
            f"{proposal.status!r}. One of the two is wrong; the tree "
            f"decides which")
    for path in proposal.paths:
        problems.extend(_path_problems(proposal, path, body))
    return problems


def _path_problems(proposal: Proposal, path: str, body: str) -> list[str]:
    """The tree and the page, on one declared path."""
    problems: list[str] = []
    exists = (REPO / path).exists()
    if proposal.status == SHIPPED and not exists:
        problems.append(
            f"proposal {proposal.number} is published as shipped and "
            f"{path} is not in the tree. Either it moved -- say so "
            f"here -- or the page is claiming something that is not "
            f"there")
    if proposal.status == OPEN and exists:
        problems.append(
            f"proposal {proposal.number} is published as open and "
            f"{path} exists. Somebody built it: the page has to say "
            f"what shipped, where it lives, and what it still owes, "
            f"the way proposals 1 to 6 do")
    if f"`{path}`" not in body:
        problems.append(
            f"{DOC}: proposal {proposal.number} never names `{path}`, "
            f"which is the path this file measures its status on. A "
            f"reader cannot check a status against evidence the page "
            f"does not point at")
    return problems


def _summary_problems(proposals: tuple[Proposal, ...], text: str) -> list[str]:
    # Matched against the page with runs of whitespace collapsed to one space,
    # so re-wrapping the opening paragraph does not break the count.
    found = list(SUMMARY.finditer(re.sub(r"\s+", " ", text)))
    if len(found) != 1:
        return [f"{DOC}: the sentence counting the proposals is stated "
                f"{len(found)} times, so the page's own summary of itself is "
                f"held to nothing: {SUMMARY.pattern}"]
    expected = {
        "total": _spell(len(proposals)),
        "shipped": _spell(sum(1 for p in proposals if p.status == SHIPPED)),
        "open": _spell(sum(1 for p in proposals if p.status == OPEN)),
    }
    actual = found[0].groupdict()
    return [f"{DOC}: the summary sentence says {key} is {actual[key]!r}; the "
            f"declarations say {want!r}"
            for key, want in expected.items() if actual[key] != want]


def census(proposals: tuple[Proposal, ...] = PROPOSALS) -> tuple[int, int, int]:
    """(proposals, shipped, declared paths). The denominator the green line
    would otherwise be missing: `every proposal matches` says nothing about
    how many paths that was."""
    return (len(proposals),
            sum(1 for p in proposals if p.status == SHIPPED),
            sum(len(p.paths) for p in proposals))


def main(argv: list[str] | None = None) -> int:
    try:
        problems = check()
    except Stale as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"\n{len(problems)} declaration(s) in {DOC} disagree with this "
              f"repository.", file=sys.stderr)
        return 1
    total, shipped, paths = census()
    print(f"expansion: {shipped} of {total} proposals in {DOC} are published "
          f"as shipped")
    print(f"           {paths} declared path(s) checked against the tree: "
          f"present where the page says shipped, absent where it says open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
