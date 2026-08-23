"""Baseline regression comparison.

A baseline is a small, committed record distilled from a previous report: its
provenance and one line per suite. It is a separate document rather than a
copy of the report so that comparing does not nest reports inside reports, and
so that the thing a repository commits as "the bar we are holding" is short
enough to read in a code review.

Two rules govern the comparison, and the second one is the point:

1. **Verdict flips are always named.** PASS to FAIL, FAIL to PASS, a suite
   that appeared, a suite that vanished. These are categorical and remain
   meaningful whatever else changed.
2. **Numeric comparison is refused when the runs are not comparable.** If the
   dataset hash or the judge configuration hash differs, the two scores were
   produced by different instruments against different evidence, and
   subtracting them produces a number that looks like a measurement and is
   not. The harness says so, in the report, instead.

That refusal is the whole reason the tamper drill works. Editing evidence and
re-sealing gives you a green-looking run; it also changes the dataset hash, so
every subsequent comparison against the committed baseline announces that the
evidence moved.

Where a comparison *is* possible, each moved suite is checked against its own
minimum detectable effect: a drop smaller than the MDE is reported as not
distinguishable from noise, so nobody chases a two-point wobble a 26-item
sample could never have resolved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from .hashing import canonical_json, sha256_text

BASELINE_FORMAT = "plumbline-baseline"
BASELINE_FORMAT_VERSION = 3


class BaselineError(Exception):
    """The baseline file is missing or unusable (configuration error)."""


def build_baseline(report: dict[str, Any]) -> dict[str, Any]:
    """Distil a report into the record a repository commits as its bar."""
    provenance = report["provenance"]
    return {
        "format": BASELINE_FORMAT,
        "format_version": BASELINE_FORMAT_VERSION,
        "source_run_id": provenance["run_id"],
        "harness_version": provenance["harness_version"],
        # A pre-release version string is the same on every commit, so on its
        # own it cannot tell a reviewer whether the instrument moved. The
        # source digest can.
        "harness_source_sha256": provenance.get("harness_source_sha256"),
        "seed": provenance["seed"],
        "dataset_sha256": provenance["dataset_sha256"],
        "dataset_id": provenance["dataset_id"],
        "judge_config_sha256": provenance["judge_config_sha256"],
        # A hash cannot tell a reader what kind of instrument set this bar.
        # A committed baseline produced by a model judge should say so on its
        # own face, not only in the report it came from.
        "judge_kind": provenance.get("judge_kind"),
        "judge_deterministic": bool(
            (report.get("judge") or {}).get("deterministic", True)),
        "target": report.get("target"),
        "verdict": report["verdict"],
        "suites": [
            {
                "suite": s["suite"],
                "score": s["score"],
                "floor": s["floor"],
                "verdict": s["verdict"],
                "n": s["n"],
            }
            for s in report["suites"]
        ],
    }


def write_baseline(baseline: dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def load_baseline(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise BaselineError(
            f"baseline file not found: {path}. A comparison was requested and "
            f"cannot be made; fix the path or drop the baseline setting."
        )
    try:
        with open(path, encoding="utf-8") as f:
            baseline = cast(dict[str, Any], json.load(f))
    except (OSError, json.JSONDecodeError) as e:
        raise BaselineError(f"unreadable baseline {path}: {e}") from e
    if baseline.get("format") != BASELINE_FORMAT:
        raise BaselineError(
            f"{path} is not a Plumbline baseline record (expected format "
            f"'{BASELINE_FORMAT}'; generate one with `plumbline baseline`)"
        )
    if baseline.get("format_version") != BASELINE_FORMAT_VERSION:
        raise BaselineError(
            f"{path}: unsupported baseline format_version "
            f"{baseline.get('format_version')!r} (supported: "
            f"{BASELINE_FORMAT_VERSION})"
        )
    for required in ("dataset_sha256", "judge_config_sha256", "suites"):
        if required not in baseline:
            raise BaselineError(f"{path}: baseline is missing '{required}'")
    return baseline


def baseline_digest(baseline: dict[str, Any]) -> str:
    """Identity of a baseline document, folded into the run id so that a run
    compared against a different bar is a different run."""
    return sha256_text(canonical_json(baseline))


def compare(report: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Compare a finished report against a baseline record."""
    provenance = report["provenance"]
    current = {s["suite"]: s for s in report["suites"]}
    previous = {s["suite"]: s for s in baseline["suites"]}

    refusals = []
    if provenance["dataset_sha256"] != baseline["dataset_sha256"]:
        refusals.append(
            f"the dataset hash differs: this run scored "
            f"{provenance['dataset_id']}, the baseline scored "
            f"{baseline.get('dataset_id', baseline['dataset_sha256'][:12])}. "
            f"The evidence changed, so the scores are not comparable numbers."
        )
    if provenance["judge_config_sha256"] != baseline["judge_config_sha256"]:
        refusals.append(
            f"the judge configuration hash differs: this run used "
            f"{provenance['judge_config_sha256'][:12]}, the baseline used "
            f"{baseline['judge_config_sha256'][:12]}. The scoring rules "
            f"changed, so the scores are not comparable numbers."
        )
    comparable = not refusals

    caveats = []
    if provenance["harness_version"] != baseline.get("harness_version"):
        caveats.append(
            f"harness version differs ({baseline.get('harness_version')} -> "
            f"{provenance['harness_version']}); suite implementations may have "
            f"changed even though the hashes match"
        )
    if (provenance.get("harness_source_sha256")
            and baseline.get("harness_source_sha256")
            and provenance["harness_source_sha256"]
            != baseline["harness_source_sha256"]):
        caveats.append(
            f"the harness source differs "
            f"({baseline['harness_source_sha256'][:12]} -> "
            f"{provenance['harness_source_sha256'][:12]}); the instrument's "
            f"own code changed between these two runs, so a moved score may "
            f"be the harness rather than the target"
        )
    if provenance["seed"] != baseline.get("seed"):
        caveats.append(
            f"seed differs ({baseline.get('seed')} -> {provenance['seed']}); "
            f"bootstrap intervals and MDEs will move slightly"
        )
    floor_changes = [
        f"{suite_id} {previous[suite_id]['floor']} -> {current[suite_id]['floor']}"
        for suite_id in sorted(set(current) & set(previous))
        if previous[suite_id]["floor"] != current[suite_id]["floor"]
    ]
    if floor_changes:
        caveats.append(
            "floors changed, so verdict changes may reflect the bar moving "
            "rather than the target: " + "; ".join(floor_changes)
        )

    flipped = [
        {"suite": suite_id,
         "was": previous[suite_id]["verdict"],
         "now": current[suite_id]["verdict"]}
        for suite_id in sorted(set(current) & set(previous))
        if previous[suite_id]["verdict"] != current[suite_id]["verdict"]
    ]

    moved = None
    if comparable:
        moved = []
        for suite_id in sorted(set(current) & set(previous)):
            delta = round(current[suite_id]["score"] - previous[suite_id]["score"], 4)
            if delta == 0.0:
                continue
            mde = current[suite_id].get("mde")
            entry = {
                "suite": suite_id,
                "baseline_score": previous[suite_id]["score"],
                "score": current[suite_id]["score"],
                "delta": delta,
                "mde": mde,
            }
            if mde is None:
                entry["detectable"] = None
                entry["note"] = ("this suite reports no minimum detectable "
                                 "effect, so the move cannot be qualified")
            else:
                entry["detectable"] = abs(delta) >= mde
                if not entry["detectable"]:
                    entry["note"] = (
                        f"the move is smaller than this suite's minimum "
                        f"detectable effect ({mde}); it is not distinguishable "
                        f"from noise at this sample size"
                    )
            moved.append(entry)

    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))

    # A suite in the bar that this run did not run is missing coverage, not a
    # clean result. "No verdict changed and no score moved" was true of the
    # suites the two runs share and read as a clean bill of the whole run, so
    # disabling a suite — the one edit that removes a check entirely — was the
    # one edit the summary line reported as nothing happening. The counts and
    # the names lead the summary now, and the sentence about movement says
    # which suites it is about.
    coverage_change = []
    if removed:
        coverage_change.append(
            f"{len(removed)} suite(s) the baseline holds were not run "
            f"({', '.join(removed)})"
        )
    if added:
        coverage_change.append(
            f"{len(added)} suite(s) not in the baseline were run "
            f"({', '.join(added)})"
        )

    if not comparable:
        core = ("numeric comparison refused; verdict changes are still "
                "named below")
    elif flipped:
        core = f"{len(flipped)} suite verdict(s) changed since the baseline"
    elif moved:
        core = (f"no verdict changed; {len(moved)} suite score(s) moved "
                f"without crossing a floor")
    elif coverage_change:
        core = "nothing moved among the suites both runs ran"
    else:
        core = "no verdict changed and no score moved"
    summary = "; ".join([*coverage_change, core])

    return {
        "comparable": comparable,
        "summary": summary,
        "against": {
            "source_run_id": baseline.get("source_run_id"),
            "dataset_id": baseline.get("dataset_id",
                                       baseline["dataset_sha256"][:12]),
            "harness_version": baseline.get("harness_version"),
            "judge_kind": baseline.get("judge_kind"),
            "baseline_sha256": baseline_digest(baseline),
        },
        "refusals": refusals,
        "caveats": caveats,
        "verdict_change": (
            None if baseline.get("verdict") == report["verdict"]
            else {"was": baseline.get("verdict"), "now": report["verdict"]}
        ),
        "flipped_suites": flipped,
        "moved_suites": moved,
        "added_suites": added,
        "removed_suites": removed,
    }


def render_markdown(comparison: dict[str, Any]) -> list[str]:
    """Markdown lines for the report's regression section."""
    lines = ["## Regression against baseline", ""]
    against = comparison["against"]
    lines.append(
        f"Baseline run `{against['source_run_id']}`, dataset "
        f"`{against['dataset_id']}`, harness `{against['harness_version']}`, "
        f"judge `{against.get('judge_kind')}`."
    )
    lines.append("")
    if not comparison["comparable"]:
        lines.append("**Numeric comparison refused.**")
        lines.append("")
        for reason in comparison["refusals"]:
            lines.append(f"- {reason}")
        lines.append("")
        lines.append(
            "Comparing incomparable runs would produce numbers that look like "
            "measurements. Verdict changes are categorical and are still "
            "reported."
        )
        lines.append("")
    for caveat in comparison["caveats"]:
        lines.append(f"- Caveat: {caveat}")
    if comparison["caveats"]:
        lines.append("")

    change = comparison["verdict_change"]
    if change:
        lines.append(f"Overall verdict: **{change['was']} → {change['now']}**.")
        lines.append("")

    if comparison["flipped_suites"]:
        lines.append("Suites whose verdict changed:")
        lines.append("")
        for flip in comparison["flipped_suites"]:
            lines.append(f"- `{flip['suite']}`: {flip['was']} → {flip['now']}")
        lines.append("")
    else:
        lines.append("No suite verdict changed.")
        lines.append("")

    for label, suites in (("Suites added since the baseline",
                           comparison["added_suites"]),
                          ("Suites in the baseline but not in this run",
                           comparison["removed_suites"])):
        if suites:
            lines.append(f"{label}: {', '.join(f'`{s}`' for s in suites)}.")
            lines.append("")

    moved = comparison["moved_suites"]
    if moved is None:
        lines.append("Score movement is not reported: see the refusal above.")
        lines.append("")
    elif moved:
        lines.append("| Suite | Baseline | Now | Delta | MDE | Detectable? |")
        lines.append("|---|---|---|---|---|---|")
        for entry in moved:
            mde = "n/a" if entry["mde"] is None else f"{entry['mde']:.4f}"
            detectable = {True: "yes", False: "no — inside the noise floor",
                          None: "unknown"}[entry["detectable"]]
            lines.append(
                f"| {entry['suite']} | {entry['baseline_score']:.4f} | "
                f"{entry['score']:.4f} | {entry['delta']:+.4f} | {mde} | "
                f"{detectable} |"
            )
        lines.append("")
    else:
        lines.append("No suite score moved.")
        lines.append("")
    return lines


def summarize_for_terminal(comparison: dict[str, Any]) -> list[str]:
    """The build-log lines. Everything the comparison found has to reach here.

    The markdown report and the JSON have named added and removed suites since
    this comparison existed; these lines did not, and these lines are what a
    build log shows. So dropping a suite from a target's configuration printed
    `baseline: no verdict changed and no score moved` and exit 0 — a check that
    stopped running, rendered as nothing having happened.
    """
    lines = [f"baseline: {comparison['summary']}"]
    for reason in comparison["refusals"]:
        lines.append(f"  REFUSED: {reason}")
    for caveat in comparison["caveats"]:
        lines.append(f"  caveat:  {caveat}")
    # Ahead of the flips and the moves: a suite that did not run has no score
    # to move and no verdict to flip, so it appears nowhere below.
    for suite_id in comparison.get("removed_suites") or []:
        lines.append(
            f"  NOT RUN: {suite_id} is in the baseline and was not run; this "
            f"run checked less than the bar it is measured against")
    for suite_id in comparison.get("added_suites") or []:
        lines.append(
            f"  added:   {suite_id} was run and is not in the baseline; it has "
            f"no bar to be compared against")
    for flip in comparison["flipped_suites"]:
        lines.append(f"  flipped: {flip['suite']} {flip['was']} -> {flip['now']}")
    for entry in comparison["moved_suites"] or []:
        tail = "" if entry["detectable"] else "  (inside the noise floor)"
        lines.append(f"  moved:   {entry['suite']} {entry['delta']:+.4f}{tail}")
    return lines
