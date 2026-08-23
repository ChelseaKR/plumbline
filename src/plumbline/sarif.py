"""Project a finished report onto SARIF 2.1.0, so a consuming repository's
pull request can carry a Plumbline finding the way it already carries a
linter finding, instead of only a pass/fail exit code.

The two real consumers documented in the README — `ChelseaKR/cairn` and
`ChelseaKR/fare-policy-assistant` — pin this harness and run it on every pull
request, and neither makes it a required check yet: "today it reports rather
than blocks." A human still has to open `report.md` to see which item failed
and why. This is a second, machine-readable rendering of exactly the same
per-item records the reports already carry — no new measurement, no new
suite, nothing scored differently — that GitHub's `upload-sarif` action can
turn into inline annotations.

**What this is not.** A SARIF `result` models a rule violated at a location
in a file; a Plumbline finding is a suite's judgment about one dataset item,
which has no line number. Every result below carries a *logical* location
(the item id, or the suite's own identifier for it — a fact pair, a
structural check name) rather than a fabricated line, because a suite score
is not a line number and pretending otherwise would be exactly the kind of
overclaim this harness argues against everywhere else. Consumers whose
tooling expects a physical location will not get inline-diff annotations
from this; they will still get the finding, its message, and its severity in
GitHub's Security tab.

Only failing and UNVERIFIABLE per-item records become SARIF results. A
passing item is not a finding, the same way a clean lint pass emits nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .suites import UNVERIFIABLE

SARIF_FILENAME = "sarif.json"

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
INFORMATION_URI = "https://github.com/ChelseaKR/plumbline"

LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
LEVEL_NOTE = "note"


def _record_id(record: dict[str, Any]) -> str:
    """The identifier a record carries under whichever key this suite uses.

    `item` is near-universal; `accessibility` uses `check` (it scores fixed
    structural checks, not dataset items — see its "n/a" CI/MDE in every
    report); `cross_language` uses `pair`, because its unit of comparison is
    two items, not one. Falling through to a fixed placeholder rather than
    raising keeps a suite this module has not seen from silently dropping
    every one of its findings.
    """
    if record.get("item"):
        return str(record["item"])
    if record.get("check"):
        return str(record["check"])
    pair = record.get("pair")
    if pair:
        return "|".join(str(p) for p in pair)
    return "(unidentified item)"


def _rule(suite: dict[str, Any]) -> dict[str, Any]:
    metric = (suite.get("details") or {}).get("metric")
    return {
        "id": suite["suite"],
        "shortDescription": {"text": f"Plumbline suite: {suite['suite']}"},
        "fullDescription": {
            "text": metric or f"Plumbline `{suite['suite']}` suite finding.",
        },
        "helpUri": INFORMATION_URI,
        "properties": {
            "floor": suite["floor"],
            "plumbline:suite": suite["suite"],
        },
    }


def _unverifiable_rule(suite_id: str) -> dict[str, Any]:
    return {
        "id": f"{suite_id}.unverifiable",
        "shortDescription": {
            "text": f"Plumbline suite {suite_id}: item excluded, not a pass",
        },
        "fullDescription": {
            "text": (
                "The evidence for this item did not let the suite check it "
                "— excluded from the score and never counted as a pass. "
                "See report.md's coverage line for this suite."
            ),
        },
        "helpUri": INFORMATION_URI,
    }


def _result(suite_id: str, record: dict[str, Any]) -> dict[str, Any]:
    item_id = _record_id(record)
    if record.get("verdict") == UNVERIFIABLE:
        rule_id = f"{suite_id}.unverifiable"
        level = LEVEL_NOTE
        message = record.get("note") or f"{suite_id}: {item_id} is UNVERIFIABLE"
    else:
        rule_id = suite_id
        # Bumped to LEVEL_ERROR by the caller when this item is one of the
        # suite's own hard_failures; a plain flagged item stays a warning.
        level = LEVEL_WARNING
        message = record.get("note") or (
            f"{suite_id} flagged {item_id} (score "
            f"{record.get('score', 0.0):.2f})"
        )
    return {
        "ruleId": rule_id,
        "level": level,
        "message": {"text": message},
        "locations": [{
            "logicalLocations": [{
                "fullyQualifiedName": item_id,
                "kind": "unknown",
            }],
        }],
        "properties": {"plumbline:suite": suite_id, "plumbline:item": item_id},
    }


def build_sarif(report: dict[str, Any]) -> dict[str, Any]:
    """The report, projected onto one SARIF run.

    Load-bearing item failures — the ones named in a suite's own
    `hard_failures`, which fail it regardless of its pooled score — are
    `error`. Ordinary flagged items are `warning`. UNVERIFIABLE items are `note`,
    under a suite-specific `<suite>.unverifiable` rule so a reader (and a
    PR's annotation count) cannot mistake "could not be checked" for "was
    checked and failed".
    """
    rules: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    seen_rules: set[str] = set()
    for suite in report.get("suites", []):
        hard = set(suite.get("hard_failures") or [])
        rule = _rule(suite)
        rules.append(rule)
        seen_rules.add(rule["id"])
        has_unverifiable = False
        for record in suite.get("items", []):
            if record.get("verdict") == UNVERIFIABLE:
                has_unverifiable = True
                results.append(_result(suite["suite"], record))
                continue
            score = record.get("score")
            if score is None or score >= 1.0:
                continue  # a pass is not a finding
            result = _result(suite["suite"], record)
            if _record_id(record) in hard:
                result["level"] = LEVEL_ERROR
            results.append(result)
        if has_unverifiable:
            unverifiable_id = f"{suite['suite']}.unverifiable"
            if unverifiable_id not in seen_rules:
                rules.append(_unverifiable_rule(suite["suite"]))
                seen_rules.add(unverifiable_id)

    provenance = report.get("provenance", {})
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [{
            "tool": {
                "driver": {
                    "name": "plumbline",
                    "informationUri": INFORMATION_URI,
                    "version": provenance.get("harness_version", "0.0.0"),
                    "rules": rules,
                },
            },
            "results": results,
            "properties": {
                "plumbline:verdict": report.get("verdict"),
                "plumbline:run_id": provenance.get("run_id"),
                "plumbline:dataset_sha256": provenance.get("dataset_sha256"),
            },
        }],
    }


def write_sarif(report: dict[str, Any], run_dir: Path) -> Path:
    """Write sarif.json next to a run's report.json/report.md."""
    out = Path(run_dir) / SARIF_FILENAME
    with open(out, "w", encoding="utf-8") as f:
        json.dump(build_sarif(report), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return out
