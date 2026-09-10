#!/usr/bin/env python3
"""Hold the prose to the same evidence the published page is held to.

`tools/build_site.py --check` proves `site/index.html` is byte-for-byte what
the committed evidence produces, and `make verify` runs it. Nothing held
`README.md` or `DESIGN.md` to anything, and the gap showed. The demo bundle
grew from 174 items to 178; the generated page said 178 the moment it was
rebuilt, and three sentences in the README went on saying 174 -- together with
the score derived from one of them, published as 0.9943 where 177 of 178 is
0.9944. The same paragraph in `DESIGN.md` still described a 174-item bundle of
48 source passages when the bundle held 178 items and 74.

The page is checked by regenerating it. A README cannot be: it is mostly
argument, and a tool that owned every byte of it would own the argument too.
So this checks the *numbers* instead. Each claim below is an anchored pattern
with the figures punched out of it, and every figure is computed from the same
committed artifacts the page is built from:

* `audits/*/report.json`, which `make reproduce` proves is byte-for-byte what
  this code produces from the committed bundle;
* `proof/matrix.json`, which `tests/test_defect_matrix.py` regenerates on
  every test run and compares;
* `datasets/riverbend-demo/`, whose every byte is sealed in `checksums.json`
  and regenerated from its own script by `tests/test_demo_bundle.py`.

One claim is not read from an artifact: the test count, which is counted by
discovering the suite. There is no committed file that records it, and a
figure that moves on almost every pull request is exactly the one that goes
stale first.

A claim whose anchor no longer matches is a failure, not a silent pass.
Rewording a sentence this file names is meant to be a decision rather than a
side effect: the alternative is a check that quietly drifts off its subject
and keeps reporting green about a sentence nobody can find.

    python3 tools/check_claims.py

Exit 0 when every claim matches the evidence, 1 otherwise. No network, no
clock, no randomness: the result is a pure function of the repository, which
is the property the reports themselves have.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLE = REPO / "datasets" / "riverbend-demo"

# The suite the MDE paragraph names as the exception. It is named here rather
# than found by taking the largest, because the paragraph names it too: if a
# second under-powered suite appeared, the band below would widen, the claim
# would go red, and a person would decide how to say so.
SMALL_SUITE = "conversational_integrity"

WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
         "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty")


class Stale(Exception):
    """A published figure and the evidence behind it disagree."""


def _spell(n: int) -> str:
    if not 0 <= n < len(WORDS):
        raise Stale(f"no spelling for {n}; the claim needs rewriting by hand")
    return WORDS[n]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines() if line]


def _committed_report() -> dict:
    reports = sorted((REPO / "audits").glob("*/report.json"))
    if len(reports) != 1:
        raise Stale(
            f"expected exactly one committed audit, found {len(reports)}")
    return json.loads(reports[0].read_text(encoding="utf-8"))


def _matrix_note(matrix: dict, case_id: str) -> str:
    for case in matrix["cases"]:
        if case["case"] == case_id:
            note = case["note"]
            if not note:
                raise Stale(f"the {case_id} case carries no note to quote")
            return str(note)
    raise Stale(f"no {case_id} case in proof/matrix.json")


def _test_count() -> int:
    """Count the suite by discovering it, the way `make test` runs it."""
    for path in (REPO / "src", REPO / "tests"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    loader = unittest.TestLoader()
    suite = loader.discover(str(REPO / "tests"))
    if loader.errors:
        raise Stale(
            "test discovery reported import errors, so any count from it "
            f"would be a guess: {loader.errors}")

    def count(node) -> int:
        if isinstance(node, unittest.TestSuite):
            return sum(count(child) for child in node)
        return 1

    total = count(suite)
    if total == 0:
        raise Stale("discovered no tests at all, which cannot be right")
    return total


def facts() -> dict[str, str]:
    """Every figure the claims below are allowed to assert, computed once."""
    report = _committed_report()
    matrix = json.loads(
        (REPO / "proof" / "matrix.json").read_text(encoding="utf-8"))
    suites = {s["suite"]: s for s in report["suites"]}

    tolerated = _matrix_note(matrix, "refusal-one-under-refusal")
    quoted = re.search(
        r"out of ([0-9]+) items scores ([0-9.]+) and passes", tolerated)
    if not quoted:
        raise Stale(
            "the defect matrix's tolerated-refusal note no longer states an "
            f"item count and a score, so the README cannot be held to it: "
            f"{tolerated!r}")

    band = [s["mde"] for name, s in suites.items()
            if s["mde"] is not None and name != SMALL_SUITE]
    if not band:
        raise Stale("no suite outside the small one reports an MDE")
    small = suites.get(SMALL_SUITE)
    if small is None or small["mde"] is None:
        raise Stale(f"{SMALL_SUITE} is not in the report, or reports no MDE")

    items = _jsonl(BUNDLE / "items.jsonl")
    sources = _jsonl(BUNDLE / "sources.jsonl")

    return {
        "items": str(report["dataset"]["items"]),
        "suites": _spell(len(report["suites"])),
        "tolerated_items": quoted.group(1),
        "tolerated_score": quoted.group(2),
        "mde_low": f"{min(band):.3f}",
        "mde_high": f"{max(band):.3f}",
        "small_n": str(small["n"]),
        "small_mde": f"{small['mde']:.3f}",
        "tests": str(_test_count()),
        "bundle_items": str(len(items)),
        "bundle_en": str(sum(1 for i in items if i.get("lang") == "en")),
        "bundle_es": str(sum(1 for i in items if i.get("lang") == "es")),
        "bundle_sources": str(len(sources)),
        "bundle_facts": str(len({i["fact_id"] for i in items
                                 if i.get("fact_id")})),
        "bundle_adversarial": str(sum(1 for i in items if i.get("adversarial"))),
    }


@dataclass(frozen=True)
class Claim:
    doc: str
    what: str
    # Matched against the document with runs of whitespace collapsed to one
    # space, so re-wrapping a paragraph does not break a claim about it.
    pattern: str
    expect: Callable[[dict[str, str]], dict[str, str]]


CLAIMS: tuple[Claim, ...] = (
    Claim(
        doc="README.md",
        what="what the floors tolerate",
        pattern=(r"One under-refusal out of (?P<items>[0-9]+) items scores "
                 r"(?P<score>[0-9.]+) and passes"),
        expect=lambda f: {"items": f["tolerated_items"],
                          "score": f["tolerated_score"]},
    ),
    Claim(
        doc="README.md",
        what="the pooled movement the tamper drill produces",
        pattern=(r"Across (?P<items>[0-9]+) items the planted fabrication "
                 r"moves `accuracy`"),
        expect=lambda f: {"items": f["items"]},
    ),
    Claim(
        doc="README.md",
        what="the minimum detectable effect the grown bundle reports",
        pattern=(r"At (?P<items>[0-9]+) items the same suites report "
                 r"\*\*(?P<low>[0-9.]+) to (?P<high>[0-9.]+)\*\*"),
        expect=lambda f: {"items": f["items"], "low": f["mde_low"],
                          "high": f["mde_high"]},
    ),
    Claim(
        doc="README.md",
        what="the under-powered suite the MDE paragraph names",
        pattern=(r"`" + SMALL_SUITE + r"` scores only \*\*(?P<n>[0-9]+)\*\* "
                 r"multi-turn items and reports an MDE of "
                 r"\*\*(?P<mde>[0-9.]+)\*\*"),
        expect=lambda f: {"n": f["small_n"], "mde": f["small_mde"]},
    ),
    Claim(
        doc="README.md",
        what="how many scoring suites the harness ships",
        pattern=r"is implemented: (?P<suites>[a-z]+) scoring suites",
        expect=lambda f: {"suites": f["suites"]},
    ),
    Claim(
        doc="README.md",
        what="the size of the test suite",
        pattern=r"(?P<tests>[0-9]+) tests, standard library only",
        expect=lambda f: {"tests": f["tests"]},
    ),
    Claim(
        doc="DESIGN.md",
        what="what the demonstration bundle is made of",
        pattern=(r"\*\*(?P<items>[0-9]+) items \((?P<en>[0-9]+) en, "
                 r"(?P<es>[0-9]+) es\)\*\*, a bilingual corpus of "
                 r"(?P<sources>[0-9]+) source passages over "
                 r"(?P<facts>[0-9]+) facts"),
        expect=lambda f: {"items": f["bundle_items"], "en": f["bundle_en"],
                          "es": f["bundle_es"], "sources": f["bundle_sources"],
                          "facts": f["bundle_facts"]},
    ),
    Claim(
        doc="DESIGN.md",
        what="how many adversarial probes the bundle carries",
        pattern=r"load-bearing numeric facts, (?P<probes>[0-9]+) adversarial",
        expect=lambda f: {"probes": f["bundle_adversarial"]},
    ),
)


#: The documents a claim may be anchored in, each with the reason it is a
#: claims surface rather than narration. The list is self-limiting in both
#: directions: a claim naming a document that is not here is refused, and a
#: document here that no claim binds a figure in is refused too, because a
#: declared claims surface with nothing anchored in it is the whole subject of
#: this file wearing a different hat.
GATED_DOCUMENTS: dict[str, str] = {
    "README.md": (
        "the project's own account of what it measures, and where every "
        "figure a reader meets first is published"),
    "DESIGN.md": (
        "the design record; the demonstration bundle's composition is stated "
        "here and nowhere else"),
}

#: One published figure. `0.9944` is one figure and not two, so the decimal
#: point is inside the token: a census whose tokens disagree with what a claim
#: captures cannot be read as a share of anything.
NUMERAL = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")


#: A claim anchors ONE sentence. Every figure in this repository is restated
#: two or three more times, and a restatement is exactly where the drift went:
#: on 2026-09-08 `DESIGN.md` said `174 items` six times and `fourteen suites`
#: three times while the evidence said 178 and fifteen, and the sentence the
#: claims above do anchor -- `**178 items (89 en, 89 es)**`, in the same file --
#: was right. So the gate held the one sentence it was pointed at and the
#: document around it was wrong.
#:
#: The two checks below are the restatement half. Neither carries a number a
#: human maintains: the suite ids and the bundle size are read from the same
#: committed artifacts the claims are, so they move when the evidence moves.
#: That is deliberate -- the alternative considered and rejected was six more
#: `Claim` rows, which is the hand-maintained counter that jams a queue.

#: Where DESIGN.md inventories the suites. Every suite id in the committed
#: report has to be named inside it. Scoped to the section rather than to the
#: file because the roadmap table names every suite in passing, so a
#: whole-document membership test passes over an inventory missing one -- which
#: is how `conversational_integrity` sat outside this section for three weeks.
SUITE_INVENTORY = ("DESIGN.md", "## Suites")

#: A heading that dates itself is a record of what was observed then, not a
#: claim about now. Rewriting `## Acceptance record (verified at M9, clean
#: checkout)` so its figures read true today destroys the thing it is for.
#: Recognised structurally -- a year, or a heading that names itself a record
#: -- rather than by listing line numbers, which move on every edit.
DATED_RECORD_HEADING = re.compile(r"\b20\d\d\b|acceptance record|roadmap",
                                  re.IGNORECASE)

#: Live sentences that say `N items` about some population other than the
#: bundle. Each entry must be observed in the live prose or this file fails:
#: an exemption for a sentence nobody writes is an exemption that quietly
#: covers the next one somebody does write. Same rule the claim patterns are
#: held to.
EXEMPT_ITEM_PHRASES: tuple[tuple[str, str], ...] = (
    ("At 26 items",
     "the bundle before it was grown, named so the comparison has two ends"),
    ("96 items scored twice with the same number",
     "the accuracy/fairness overlap the report counts, not the bundle"),
)

ITEM_COUNT = re.compile(r"\b(\d+) items\b")


def _read(doc: str) -> str:
    """The document, whitespace-collapsed the way the claims are matched."""
    return re.sub(r"\s+", " ", _raw(doc))


def _raw(doc: str) -> str:
    """The document as written. Headings are line-anchored, so the section
    walk below needs the newlines the claim matcher throws away."""
    return (REPO / doc).read_text(encoding="utf-8")


def _sections(text: str) -> list[tuple[list[str], str]]:
    """The document as (enclosing headings, body) pairs.

    A `###` inside a dated `##` inherits the date, so the enclosing headings
    are carried rather than only the nearest one.
    """
    out: list[tuple[list[str], str]] = []
    stack: list[tuple[int, str]] = []
    body: list[str] = []
    for line in text.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not heading:
            body.append(line)
            continue
        out.append(([h for _, h in stack], "\n".join(body)))
        body = []
        level = len(heading.group(1))
        stack = [(lvl, h) for lvl, h in stack if lvl < level]
        stack.append((level, heading.group(2)))
    out.append(([h for _, h in stack], "\n".join(body)))
    return out


def live_prose(doc: str, text: str | None = None) -> str:
    """The document minus every section under a heading that dates itself."""
    if text is None:
        text = _raw(doc)
    return "\n".join(
        body for headings, body in _sections(text)
        if not any(DATED_RECORD_HEADING.search(h) for h in headings))


def restated_bundle_size(
    texts: dict[str, str] | None = None,
    size: int | None = None,
) -> tuple[int, int, int]:
    """Hold every live `N items` in the gated documents to the real bundle.

    Returns (checked, dated, exempt) so the gate can print what it looked at
    instead of only that it was happy.
    """
    if size is None:
        size = len(_jsonl(BUNDLE / "items.jsonl"))
    # The exemption list describes the *shipped* prose. Tests hand this
    # function one synthetic document at a time to prove the failure modes,
    # and "the exemptions appear nowhere" is true of every such call and means
    # nothing about the repository -- the same reason the four universe
    # refusals apply only to `CLAIMS`.
    shipped = texts is None
    if shipped:
        texts = {doc: _raw(doc) for doc in GATED_DOCUMENTS}

    seen_phrases: set[str] = set()
    checked = dated = 0
    problems: list[str] = []
    for doc, text in sorted(texts.items()):
        live = live_prose(doc, text)
        dated += (len(ITEM_COUNT.findall(text))
                  - len(ITEM_COUNT.findall(live)))
        exempt_spans = []
        for phrase, _reason in EXEMPT_ITEM_PHRASES:
            for found in re.finditer(re.escape(phrase), live):
                seen_phrases.add(phrase)
                exempt_spans.append(found.span())
        for match in ITEM_COUNT.finditer(live):
            if any(lo <= match.start() and match.end() <= hi
                   for lo, hi in exempt_spans):
                continue
            checked += 1
            if int(match.group(1)) != size:
                problems.append(
                    f"{doc}: {match.group(0)!r} — the committed bundle holds "
                    f"{size}. If this sentence is about a different "
                    f"population, name it in EXEMPT_ITEM_PHRASES with the "
                    f"reason; if it is history, put it under a dated heading")
    unobserved = sorted({p for p, _ in EXEMPT_ITEM_PHRASES} - seen_phrases)
    if shipped and unobserved:
        raise Stale(
            f"{unobserved} are exempted from the bundle-size check and appear "
            f"nowhere in the live prose. An exemption nobody's sentence needs "
            f"is an exemption covering the next one that does: delete it")
    if checked == 0:
        raise Stale(
            "the bundle-size scan read no `N items` at all in the live prose "
            "of the gated documents, which cannot be right — the anchored "
            "sentence in DESIGN.md is one. The reader has stopped matching")
    if problems:
        raise Stale("; ".join(problems))
    exempt = sum(1 for _ in EXEMPT_ITEM_PHRASES)
    return checked, dated, exempt


def suites_missing_from_the_inventory(
    text: str | None = None,
    names: list[str] | None = None,
) -> tuple[list[str], int]:
    """Suite ids the committed report carries that DESIGN.md does not name."""
    doc, heading = SUITE_INVENTORY
    if names is None:
        names = [s["suite"] for s in _committed_report()["suites"]]
    if not names:
        raise Stale("the committed report lists no suites, so this check "
                    "would pass over anything")
    if text is None:
        text = _raw(doc)
    # Membership, not position: this document opens with an H1, so every `##`
    # is nested under it and `headings[0]` is the title. Asking whether the
    # inventory heading is anywhere in the enclosing stack also picks up its
    # sub-sections, which is where most of the suites are described.
    wanted = heading.lstrip("# ").strip()
    section = [body for headings, body in _sections(text)
               if wanted in headings]
    if not section:
        raise Stale(
            f"{doc} has no {heading!r} section any more, so the suite "
            f"inventory this checks is not where SUITE_INVENTORY says it is")
    inventory = "\n".join(section)
    return [n for n in names if f"`{n}`" not in inventory], len(names)


def coverage(
    claims: tuple[Claim, ...] = CLAIMS,
    texts: dict[str, str] | None = None,
) -> dict[str, tuple[int, int]]:
    """Per gated document: numerals bound to the evidence, and numerals present.

    This is the number the green line was missing. `claims: 8 published
    figures match the committed evidence` was true and said nothing about how
    much of the two documents those eight figures covered -- and the answer
    was 15 numerals out of 490. A gate that does not state its own denominator
    reads exactly like one that examined everything.

    A figure is counted as bound when a claim captures it *and* the captured
    text is a numeral by the same tokenizer the denominator uses. A capture
    that is not a numeral -- the spelled-out suite count -- is deliberately not
    added to the numerator, because inflating it against a numeral denominator
    would be the same defect one level in.
    """
    if texts is None:
        texts = {doc: _read(doc) for doc in GATED_DOCUMENTS}
    census = {doc: [0, len(NUMERAL.findall(text))]
              for doc, text in texts.items()}
    for claim in claims:
        found = list(re.finditer(claim.pattern, texts[claim.doc]))
        if len(found) != 1:
            continue  # `check` reports this; a census cannot also fail on it.
        for value in found[0].groupdict().values():
            if value is not None and NUMERAL.fullmatch(value):
                census[claim.doc][0] += 1
    return {doc: (bound, total) for doc, (bound, total) in census.items()}


def refuse_a_universe_that_cannot_fail(
    claims: tuple[Claim, ...] = CLAIMS,
    texts: dict[str, str] | None = None,
) -> None:
    """The floor. None of these is a counter, so none of them jams a queue.

    Each refusal names a way this file could report green over a surface it
    never looked at: a claim anchored in a document nobody declared, a
    declared document with nothing anchored in it, a claim that captures no
    figure at all, and a document the numeral scan reads as empty.
    """
    if texts is None:
        texts = {doc: _read(doc)
                 for doc in set(GATED_DOCUMENTS) | {c.doc for c in claims}}
    undeclared = sorted({c.doc for c in claims} - set(GATED_DOCUMENTS))
    if undeclared:
        raise Stale(
            f"{undeclared} are anchored by a claim and are not declared claims "
            f"surfaces in GATED_DOCUMENTS, so nothing says why their prose is "
            f"held to the evidence")
    for claim in claims:
        found = list(re.finditer(claim.pattern, texts[claim.doc]))
        if len(found) != 1:
            continue
        if not any(value is not None and NUMERAL.fullmatch(value)
                   for value in found[0].groupdict().values()):
            if not any(value in WORDS
                       for value in found[0].groupdict().values()):
                raise Stale(
                    f"the claim about {claim.what} captures no figure, so it "
                    f"holds nothing to the evidence")
    for doc, (bound, total) in coverage(claims, texts).items():
        if total == 0:
            raise Stale(
                f"{doc} is a declared claims surface and the numeral scan "
                f"found nothing in it, so this file's coverage over it cannot "
                f"be read")
        if bound == 0:
            raise Stale(
                f"{doc} is declared a claims surface in GATED_DOCUMENTS and no "
                f"claim binds a figure in it. Either anchor one, or say it is "
                f"narration by removing it from GATED_DOCUMENTS")
        if bound > total:
            raise Stale(
                f"{doc} reports {bound} bound figures out of {total} present, "
                f"which means the two are not counting the same thing")

    # The two restatement refusals run last: the four above are about this
    # file's own universe, and these two are about the documents.
    missing, total_suites = suites_missing_from_the_inventory()
    if missing:
        doc, heading = SUITE_INVENTORY
        raise Stale(
            f"the committed report scores {total_suites} suites and "
            f"{doc} {heading!r} names {total_suites - len(missing)} of them: "
            f"{missing} is not in the inventory. A design record missing a "
            f"suite is how that section came to say `fourteen`")
    restated_bundle_size(None)


def check(claims: tuple[Claim, ...] = CLAIMS) -> list[str]:
    """Return one line per claim that does not match the evidence."""
    known = facts()
    texts = {doc: _read(doc)
             for doc in set(GATED_DOCUMENTS) | {c.doc for c in claims}}
    # The universe refusals are about the *shipped* set of claims. Tests hand
    # this function one deliberately broken claim at a time to prove the
    # failure modes, and "the other declared document has nothing anchored in
    # it" is true of every one of those calls and means nothing about the
    # repository. So the floor applies to the real set, which is the set the
    # gate runs.
    if claims is CLAIMS:
        refuse_a_universe_that_cannot_fail(claims, texts)

    problems: list[str] = []
    for claim in claims:
        found = list(re.finditer(claim.pattern, texts[claim.doc]))
        if not found:
            problems.append(
                f"{claim.doc}: the sentence stating {claim.what} is not there "
                f"any more, so nothing is holding it to the evidence. If it "
                f"was reworded on purpose, update the pattern in "
                f"tools/check_claims.py to match: {claim.pattern}")
            continue
        if len(found) > 1:
            problems.append(
                f"{claim.doc}: {claim.what} is stated {len(found)} times; "
                f"this file checks one of them and would leave the rest to "
                f"drift. Say it once, or give each spelling its own claim.")
            continue
        expected = claim.expect(known)
        actual = found[0].groupdict()
        for key, want in expected.items():
            if actual[key] != want:
                problems.append(
                    f"{claim.doc}: {claim.what} publishes {key} as "
                    f"{actual[key]!r}; the committed evidence says {want!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    try:
        problems = check()
    except Stale as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"\n{len(problems)} published claim(s) disagree with the "
              f"committed evidence.", file=sys.stderr)
        return 1
    census = coverage()
    bound = sum(b for b, _ in census.values())
    total = sum(t for _, t in census.values())
    per_doc = "; ".join(f"{doc} {b} of {t}"
                        for doc, (b, t) in sorted(census.items()))
    print(f"claims: {len(CLAIMS)} published figures match the committed "
          f"evidence")
    print(f"        {bound} of {total} numerals in the gated documents are "
          f"anchored to it ({per_doc})")
    print(f"        the rest are unchecked prose: this gate is evidence about "
          f"{bound} figures, not about either document")
    checked, dated, exempt = restated_bundle_size()
    missing, suites = suites_missing_from_the_inventory()
    doc, heading = SUITE_INVENTORY
    print(f"restated: {checked} live `N items` mentions hold to the committed "
          f"bundle ({dated} more sit under dated headings and are left as "
          f"written; {exempt} phrase(s) exempt with a reason)")
    print(f"          all {suites} scored suites are named in {doc} "
          f"{heading!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
