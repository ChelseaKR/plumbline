"""Suite independence: when several failures are one finding.

Fourteen red rows in a report look like fourteen problems. They are not
necessarily fourteen problems, because the suites are not fourteen independent
instruments — some of them read the same evidence, and one defect in that
evidence fails all of them at once. The defect-injection matrix
(`proof/matrix.md`) established two such couplings by planting defects and
watching what else fell over. Leaving that finding in a proof file would mean
every reader who has not opened the proof file overcounts what is wrong with
their system.

So the report says it, and says it from the run's own per-item records rather
than from an assertion in a docstring: where two coupled suites both failed,
this module looks for the items they failed on and reports whether they are
the *same* items. Two suites failing on the same input class but on different
items are two findings, and it says that too.

What it does not do is discover couplings. The declarations below are
maintained by hand from the matrix, and `tests/test_couplings.py` fails if the
matrix ever observes a multi-suite failure this file does not declare — so a
new coupling cannot stay in the proof file either.
"""

from __future__ import annotations

from .suites import CAUSE_FORBIDDEN, FAIL, SuiteResult

FORBIDDEN_LIST = "forbidden-list"
PER_ITEM_ANSWER_SCORE = "per-item-answer-score"

DECLARATIONS: list[dict] = [
    {
        "id": FORBIDDEN_LIST,
        "suites": ["adversarial", "privacy", "representational_harms"],
        "shared_input": "each item's `forbidden` list",
        "relationship": (
            "All three screen every recorded response against the item's "
            "`forbidden` list, so one emitted forbidden phrase is three "
            "failures. Observed, not assumed: the `adversarial-content-leak` "
            "case in proof/matrix.md fails all three"
        ),
        "evidence": "items each suite failed with the same recorded cause",
    },
    {
        "id": PER_ITEM_ANSWER_SCORE,
        "suites": ["accuracy", "fairness"],
        "shared_input": "the judge's per-item answer score",
        "relationship": (
            "`fairness` measures the disparity between groups of the very "
            "numbers `accuracy` pools: per-item service quality *is* the "
            "accuracy measure. A service-quality gap wide enough to breach the "
            "fairness floor necessarily moves the accuracy mean, and only "
            "accuracy's distance from its own floor decides whether that "
            "second failure appears. They cannot be read as independent "
            "evidence in either direction"
        ),
        "evidence": "items both suites scored, with the identical score",
    },
]


def _failing_items_by_cause(result: SuiteResult, cause: str) -> set[str]:
    return {r["item"] for r in result.item_records
            if r.get("cause") == cause and r.get("score") == 0.0}


def _shared_forbidden_items(results: dict[str, SuiteResult],
                            suites: list[str]) -> list[str]:
    sets = [_failing_items_by_cause(results[s], CAUSE_FORBIDDEN)
            for s in suites if s in results]
    if not sets:
        return []
    shared = set.intersection(*sets)
    return sorted(shared)


def _identically_scored_items(results: dict[str, SuiteResult],
                              suites: list[str]) -> list[str]:
    """Items every named suite scored, with the same number in each.

    Not a heuristic: it is the definitional overlap between `accuracy` and
    `fairness`, counted rather than claimed.
    """
    tables = [{r["item"]: r.get("score") for r in results[s].item_records}
              for s in suites if s in results]
    if len(tables) < 2:
        return []
    common = set(tables[0])
    for table in tables[1:]:
        common &= set(table)
    return sorted(item for item in common
                  if len({table[item] for table in tables}) == 1)


def _evidence_for(declaration: dict, results: dict[str, SuiteResult],
                  present: list[str]) -> list[str]:
    if declaration["id"] == FORBIDDEN_LIST:
        return _shared_forbidden_items(results, present)
    if declaration["id"] == PER_ITEM_ANSWER_SCORE:
        return _identically_scored_items(results, present)
    return []


def _reading(declaration: dict, failed: list[str], shared: list[str]) -> str:
    """What a reader should take from the coupling, in this run."""
    if len(failed) < 2:
        return ("Fewer than two of them failed, so nothing here is being "
                "double-counted.")
    names = ", ".join(f"`{s}`" for s in failed)
    if declaration["id"] == FORBIDDEN_LIST:
        if shared:
            return (
                f"{names} failed on the same {len(shared)} item(s) "
                f"({', '.join('`' + i + '`' for i in shared)}) through the "
                f"same shared input. Read that as ONE finding wearing "
                f"{len(failed)} hats, not {len(failed)} findings."
            )
        return (
            f"{names} failed, but on different items: no item trips more than "
            f"one of them here, so these are separate findings that happen to "
            f"read the same input."
        )
    return (
        f"{names} both failed, over {len(shared)} items they score with the "
        f"identical number. They are not independent evidence: check whether "
        f"the same items drive both before counting two findings."
    )


def analyze(results: list[SuiteResult]) -> dict:
    """The coupling disclosure for one run.

    Only declarations with at least two of their suites enabled appear: a
    coupling between suites nobody ran is noise in the report.
    """
    by_id = {r.suite_id: r for r in results}
    entries = []
    for declaration in DECLARATIONS:
        present = [s for s in declaration["suites"] if s in by_id]
        if len(present) < 2:
            continue
        failed = [s for s in present if by_id[s].verdict == FAIL]
        shared = _evidence_for(declaration, by_id, present)
        entries.append({
            "id": declaration["id"],
            "suites": present,
            "not_enabled": [s for s in declaration["suites"]
                            if s not in by_id],
            "shared_input": declaration["shared_input"],
            "relationship": declaration["relationship"],
            "failed": failed,
            "shared_items": shared,
            "shared_items_are": declaration["evidence"],
            "reading": _reading(declaration, failed, shared),
        })
    return {
        "note": (
            "Suites are not independent instruments. Where two enabled suites "
            "read the same evidence, one defect fails both, and counting red "
            "rows overcounts the findings. Each entry names a shared input; "
            "`reading` is computed from this run's own per-item records"
        ),
        "double_counting_risk": any(len(e["failed"]) > 1 for e in entries),
        "shared_inputs": entries,
    }


def render_markdown(couplings: dict) -> list[str]:
    """The section a reader sees directly under the suite table."""
    entries = couplings.get("shared_inputs") or []
    if not entries:
        return []
    lines = ["## Suite independence", ""]
    lines.append(
        "Two red rows are not always two problems. Where enabled suites read "
        "the same evidence, one defect fails more than one of them.")
    lines.append("")
    for entry in entries:
        names = ", ".join(f"`{s}`" for s in entry["suites"])
        lines.append(f"- {names} — shared input: {entry['shared_input']}. "
                     f"{entry['relationship']}.")
        emphasis = "**" if len(entry["failed"]) > 1 else ""
        lines.append(f"  {emphasis}In this run: {entry['reading']}{emphasis}")
    lines.append("")
    return lines


def summarize_for_terminal(couplings: dict) -> list[str]:
    """One line per coupling that actually produced more than one failure.

    A passing run says nothing here; a build log with three red suites should
    not make somebody chase three bugs.
    """
    lines = []
    for entry in couplings.get("shared_inputs") or []:
        if len(entry["failed"]) > 1:
            lines.append(f"coupling: {entry['reading']}"
                         .replace("`", ""))
    return lines
