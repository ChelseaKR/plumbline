"""The changelog has one shape, and the next release is cut from it.

`CHANGELOG.md` follows Keep a Changelog: `## [Unreleased]` first, then one
dated `## [X.Y.Z] - YYYY-MM-DD` section per release in reverse order, entries
grouped under `### Added` / `### Changed` / `### Fixed` and the rest, and a link
reference at the foot for every section. `plumbline-eval` is reserved on PyPI
and unpublished, so this file is what a first published release would be cut
from, and nothing was checking its shape.

Between 2026-08-27 and 2026-09-01 five merged pull requests prepended their
entries to the top of the file, above the `## [Unreleased]` heading instead of
below it. The result was 308 lines -- nine `Fixed`, one `Added` and one
`Changed` entry -- in three type headings with no release heading over them,
followed at line 318 by `## [Unreleased]` holding four older entries under
three more type headings, two of them a second `Fixed`. A reader starting at the
top could not tell which release the first three hundred lines belonged to,
because structurally they belonged to none, and a release cut by moving the
`[Unreleased]` heading would have carried them nowhere. Every gate here that
regenerates or checks a document (`site-check`, `claims-check`) is offline and
runs from the tree; this one is the same shape for the changelog.

What is checked: the first section heading is `[Unreleased]` and no type
heading or entry precedes it; releases are versioned, dated, and in descending
order; every section has a link reference and every link reference a section;
every entry sits under a type heading Keep a Changelog names; `[Unreleased]`
uses each type heading once; and the version in `pyproject.toml` has a section.

Scope. The once-per-type rule is held for `[Unreleased]` only. `[0.2.0]` was
tagged with `Added` three times and `Fixed` twice, one of those `Fixed` added
after the tag on purpose because the fix landed inside the commit the tag points
to. A released section is the record of what was published, and re-grouping it
here would be rewriting the record to satisfy the check. `[Unreleased]` is the
only section still being written to and the only one a release is cut from.

Read as text, as `test_ci_parity.py` reads the workflow: no third-party
dependencies, and a Markdown parser to check one file would cost more than it
buys. Fenced code blocks are skipped so an example inside an entry cannot pass
for a heading.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHANGELOG = REPO / "CHANGELOG.md"
PYPROJECT = REPO / "pyproject.toml"

SECTION = re.compile(r"^## \[(?P<name>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?\s*$")
TYPE = re.compile(r"^### (?P<kind>\S+)\s*$")
ENTRY = re.compile(r"^- ")
LINK = re.compile(r"^\[(?P<name>[^\]]+)\]: \S+$")
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
FENCE = re.compile(r"^\s*```")
PACKAGE_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.M)

# Keep a Changelog 1.1.0's types, and no others.
KINDS = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}


def _lines() -> list[tuple[int, str]]:
    """(line number, text) for every line outside a fenced code block."""
    out: list[tuple[int, str]] = []
    fenced = False
    for number, text in enumerate(CHANGELOG.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(text):
            fenced = not fenced
            continue
        if not fenced:
            out.append((number, text))
    return out


def _sections() -> list[dict]:
    """Each `## [...]` heading with its line number, date, and the lines under it."""
    sections: list[dict] = []
    for number, text in _lines():
        if match := SECTION.match(text):
            sections.append({"name": match["name"], "date": match["date"],
                             "line": number, "body": []})
        elif sections:
            sections[-1]["body"].append((number, text))
    return sections


def _links() -> dict[str, int]:
    return {m["name"]: n for n, t in _lines() if (m := LINK.match(t))}


class TheChangelogHasOneShape(unittest.TestCase):
    def test_the_file_was_read(self):
        """A floor. A renamed or emptied changelog would pass every check below
        over nothing."""
        self.assertTrue(CHANGELOG.is_file(), CHANGELOG)
        self.assertGreaterEqual(len(_sections()), 2, "fewer than two sections")

    def test_unreleased_is_first_and_nothing_precedes_it(self):
        """The defect this file was written for. A type heading or an entry
        above `## [Unreleased]` belongs to no release, and the next release
        would be cut without it."""
        sections = _sections()
        self.assertEqual(sections[0]["name"], "Unreleased",
                         f"first section at line {sections[0]['line']} is "
                         f"[{sections[0]['name']}], not [Unreleased]")
        first = sections[0]["line"]
        stray = [(n, t) for n, t in _lines()
                 if n < first and (TYPE.match(t) or ENTRY.match(t))]
        self.assertEqual(stray, [],
                         f"{len(stray)} heading/entry line(s) above [Unreleased] "
                         f"(line {first}); first at line {stray[0][0] if stray else 0}: "
                         f"{stray[0][1][:60] if stray else ''!r}")

    def test_releases_are_versioned_dated_and_in_reverse_order(self):
        sections = _sections()
        self.assertIsNone(sections[0]["date"], "[Unreleased] carries a date")
        releases = sections[1:]
        self.assertTrue(releases, "no released section")
        for section in releases:
            self.assertRegex(section["name"], VERSION,
                             f"line {section['line']}: [{section['name']}] is not X.Y.Z")
            self.assertIsNotNone(section["date"],
                                 f"line {section['line']}: [{section['name']}] has no date")
        versions = [tuple(int(p) for p in VERSION.match(s["name"]).groups())
                    for s in releases]
        self.assertEqual(versions, sorted(versions, reverse=True),
                         f"releases are not in descending order: {[s['name'] for s in releases]}")
        self.assertEqual(len(versions), len(set(versions)), "a version has two sections")
        dates = [s["date"] for s in releases]
        self.assertEqual(dates, sorted(dates, reverse=True),
                         f"release dates are not in reverse order: {dates}")

    def test_every_section_has_a_link_and_every_link_a_section(self):
        names = [s["name"] for s in _sections()]
        links = _links()
        self.assertEqual(set(names), set(links),
                         f"sections without a link: {sorted(set(names) - set(links))}; "
                         f"links without a section: {sorted(set(links) - set(names))}")

    def test_entries_sit_under_a_named_type_heading(self):
        """An entry directly under a release heading has no type, and a type
        Keep a Changelog does not name is a typo nothing else would catch."""
        for section in _sections():
            kind = None
            for number, text in section["body"]:
                if match := TYPE.match(text):
                    kind = match["kind"]
                    self.assertIn(kind, KINDS,
                                  f"line {number}: `### {kind}` is not a Keep a Changelog type")
                elif ENTRY.match(text):
                    self.assertIsNotNone(kind,
                                         f"line {number}: entry in [{section['name']}] "
                                         "before any `###` type heading")

    def test_unreleased_uses_each_type_once(self):
        """Two `### Fixed` headings in one section is how the entries above got
        lost: each new entry went under a fresh heading at the top. Held for
        [Unreleased] only; see the module docstring for why."""
        unreleased = _sections()[0]
        kinds = [(n, m["kind"]) for n, t in unreleased["body"] if (m := TYPE.match(t))]
        seen: dict[str, int] = {}
        for number, kind in kinds:
            self.assertNotIn(kind, seen,
                             f"line {number}: second `### {kind}` in [Unreleased] "
                             f"(first at line {seen.get(kind)})")
            seen[kind] = number

    def test_the_package_version_has_a_section(self):
        """The version `pyproject.toml` declares is the one a tag and a PyPI
        upload would carry, so the changelog has to have a section for it."""
        match = PACKAGE_VERSION.search(PYPROJECT.read_text(encoding="utf-8"))
        self.assertIsNotNone(match, "pyproject.toml has no `version = ...`")
        self.assertIn(match.group(1), [s["name"] for s in _sections()],
                      f"pyproject.toml is version {match.group(1)} and CHANGELOG.md "
                      "has no section for it")


if __name__ == "__main__":
    unittest.main()
