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


def check(claims: tuple[Claim, ...] = CLAIMS) -> list[str]:
    """Return one line per claim that does not match the evidence."""
    known = facts()
    texts = {doc: re.sub(r"\s+", " ",
                         (REPO / doc).read_text(encoding="utf-8"))
             for doc in {c.doc for c in claims}}

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
    print(f"claims: {len(CLAIMS)} published figures match the committed "
          f"evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
