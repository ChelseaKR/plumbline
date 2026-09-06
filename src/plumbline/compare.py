"""Several targets, one question set, and a table that says which differences are real.

A procurement reviewer choosing between two vendors, or a team choosing between two versions
of its own system, wants the same evidence graded against each. Today that is N audits and a
spreadsheet, and a spreadsheet does not carry the one line that matters: two scores differing
by less than the suite's minimum detectable effect are the same score.

Three refusals hold this together, and each of them is the alternative to a number that would
read as a measurement:

Different questions are not compared. If the targets' question sets or judge configuration
hashes differ, this refuses and names the hashes, exactly as `baseline.compare` refuses. Two
scores produced from different question sets are not two readings of one instrument.

What is required to match is the QUESTION SET, not the bundle. A bundle's `dataset_sha256`
covers its recorded responses, so two targets answering one question set never share it, and
refusing on it would refuse every comparison this verb exists to make. See
`question_set_digest`; this reading is recorded in the pull request for #64 and is the one
open question in this module.

A suite one target ran and another did not is not a delta of zero. It is named as not scored
by that target, and no pair is emitted for it. A missing measurement compared against a
present one is the "absence rendered as a value" defect this project exists to make loud.

A delta whose suite reports no minimum detectable effect is `not qualifiable`, never `inside
noise`. `inside noise` is a claim -- that the difference is smaller than what this sample
could detect -- and a suite with no MDE (an exhaustive census, a suite that scored nothing)
has not made it. Calling those the same thing would let the safest-sounding label stand in for
an answer nobody computed.

There is no ranking column and no composite score. The targets appear in the order given.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import sqrt
from typing import Any

from .bundle import Bundle
from .hashing import canonical_json, sha256_text, short_id

COMPARISON_FORMAT = "plumbline-comparison"
COMPARISON_FORMAT_VERSION = 1

#: The parts of a bundle that are the *questions*, as opposed to one target's answers to them.
#: `sources` is in: a passage the target was given is part of what it was asked, and a suite
#: that scores grounding against different passages is not scoring the same question.
#: `responses` is out, and `interface` is out -- both are the target's own, and requiring them
#: to match would mean only a target compared against itself could ever be compared.
QUESTION_SET_ROLES = ("items", "sources")

#: How a per-item record names the unit it scored. Most suites key by `item`; `cross_language`
#: scores a pair of items and names both under `pair`; `accessibility` scores named `check`s
#: rather than items. A record naming none of these is about something that is not a scored
#: unit, and is not comparable across targets.
_UNIT_KEYS = ("item", "pair", "check")

#: The three things a pairwise delta can be. `not_qualifiable` is deliberately not a synonym
#: for `inside_noise`: one says the difference is smaller than this sample can detect, the
#: other says nothing was computed that could say either way.
DISTINGUISHABLE = "distinguishable"
INSIDE_NOISE = "inside noise"
NOT_QUALIFIABLE = "not qualifiable"
#: No delta could be computed at all, because at least one side has no score. Kept apart from
#: the three above in the TYPE and not only in the prose: `delta` is `None` here, never `0.0`.
#: A missing measurement subtracted from a present one is not a difference of zero, and a
#: reader skimming a delta column must not be able to read one as the other.
NOT_COMPARABLE = "not comparable"


class CompareError(Exception):
    """These runs cannot be compared, and the reason names what differs."""


@dataclass(frozen=True)
class TargetRun:
    """One target's finished audit, with the position it was given on the command line."""

    position: int
    name: str
    config: str
    report: dict[str, Any]
    question_set_sha256: str

    @property
    def label(self) -> str:
        """The column heading.

        Carries the position because two identical configurations are a legitimate thing to
        compare -- it is how a reader checks that the harness gives the same answer twice --
        and they produce the same target name. Two columns headed `riverbend` would be a table
        a reader cannot read.
        """
        return f"{self.position}. {self.name}"


def question_set_digest(bundle: Bundle) -> str:
    """Identity of the questions asked, independent of the answers recorded.

    A bundle's `dataset_sha256` covers its recorded responses, so two targets answering one
    question set NEVER share it. Refusing on it, which is what the issue's literal wording
    asks for, would refuse every comparison the feature exists to make: a procurement reviewer
    holding two vendors' recordings would be told their evidence differs, which is true and
    is the whole point.

    So the thing required to match is the question set: the items and the passages, taken from
    the checksums the bundle was already verified against. Nothing new is trusted here and
    nothing new is stamped into a report -- this is a digest over digests that
    `bundle.load` has already checked.
    """
    files = bundle.manifest.get("files", {})
    material: dict[str, str] = {}
    for role in QUESTION_SET_ROLES:
        name = files.get(role)
        if name is None:
            continue
        digest = bundle.covered.get(str(name))
        if digest is None:
            raise CompareError(
                f"the bundle at {bundle.path} declares a {role} file ({name}) that no "
                f"checksum covers, so its question set cannot be identified"
            )
        material[role] = digest
    if "items" not in material:
        raise CompareError(
            f"the bundle at {bundle.path} declares no items file, so it has no question set"
        )
    return sha256_text(canonical_json(material))


def _provenance(run: TargetRun) -> dict[str, Any]:
    provenance = run.report.get("provenance")
    if not isinstance(provenance, dict):
        raise CompareError(f"{run.config} did not produce a report with provenance")
    return provenance


def refusals(runs: list[TargetRun]) -> list[str]:
    """Why these runs are not comparable, or an empty list.

    Every target is compared against the first, so the message names a pair rather than
    reporting that "the hashes differ" and leaving a reader to find out between which.
    """
    if len(runs) < 2:
        raise CompareError("comparing takes at least two targets; pass --config twice")
    first = runs[0]
    head = _provenance(first)
    reasons: list[str] = []
    for run in runs[1:]:
        other = _provenance(run)
        if first.question_set_sha256 != run.question_set_sha256:
            reasons.append(
                f"the question set differs: {first.label} was asked "
                f"{short_id(first.question_set_sha256)} (dataset "
                f"{head['dataset_sha256'][:12]}) and {run.label} was asked "
                f"{short_id(run.question_set_sha256)} (dataset "
                f"{other['dataset_sha256'][:12]}). Different questions, so the scores are not "
                f"comparable numbers. `plumbline diff` between the two bundles says what "
                f"changed."
            )
        if head["judge_config_sha256"] != other["judge_config_sha256"]:
            reasons.append(
                f"the judge configuration hash differs: {first.label} used "
                f"{head['judge_config_sha256'][:12]} and {run.label} used "
                f"{other['judge_config_sha256'][:12]}. The scoring rules are not the same, so "
                f"the scores are not comparable numbers."
            )
    return reasons


def caveats(runs: list[TargetRun]) -> list[str]:
    """Differences that do not stop the comparison but change how to read it."""
    first, head = runs[0], _provenance(runs[0])
    notes: list[str] = []
    for run in runs[1:]:
        other = _provenance(run)
        if head.get("harness_source_sha256") != other.get("harness_source_sha256"):
            notes.append(
                f"the harness source differs between {first.label} and {run.label}; the "
                f"instrument's own code changed, so a gap may be the harness rather than the "
                f"targets"
            )
        if head.get("seed") != other.get("seed"):
            notes.append(
                f"the seed differs between {first.label} ({head.get('seed')}) and "
                f"{run.label} ({other.get('seed')}); bootstrap intervals and MDEs will move "
                f"slightly"
            )
    return notes


def _unit_key(record: dict[str, Any]) -> str | None:
    for key in _UNIT_KEYS:
        value = record.get(key)
        if isinstance(value, str):
            return f"{key}:{value}"
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return f"{key}:" + " + ".join(value)
    return None


def _units(suite: dict[str, Any]) -> dict[str, dict[str, Any]]:
    units: dict[str, dict[str, Any]] = {}
    for record in suite.get("items", []):
        key = _unit_key(record)
        if key is not None:
            units[key] = record
    return units


def _governing_mde(left: dict[str, Any], right: dict[str, Any]
                   ) -> tuple[float | None, str | None]:
    """The threshold a delta between these two runs must clear, derived from both.

    Neither run's own MDE is the right number. `stats.mde_from_se` reports, for one run,
    `(z_a + z_b) * sqrt(2) * se` -- the smallest difference detectable between two independent
    runs *of that run's variance*. Comparing run A against run B, the standard error of the
    difference is `sqrt(se_A^2 + se_B^2)`, so the threshold is

        (z_a + z_b) * sqrt(se_A^2 + se_B^2)  ==  sqrt((mde_A^2 + mde_B^2) / 2)

    the root mean square of the two published MDEs. It needs nothing the report does not
    already carry, and when the two runs have equal variance it returns exactly the MDE each
    of them published, which is what that number already claims to mean.

    The alternative considered was the larger of the two, as a conservative reading of the
    issue's "MDE at the smaller n". It was rejected on measurement, not taste: a target
    answering half of a twelve-question set wrong has bimodal per-item scores and therefore a
    large MDE of its own, and taking the maximum reported that target as `inside noise`
    against a perfect one. A rule that calls a fifty-point gap noise is not conservative, it
    is broken.

    One approximation, stated because it is real: where a run scored a flat 1.0 or 0.0,
    `stats` reports the rule-of-three bound `3/n` rather than a standard error, and combining
    that through this formula treats it as though it were one. Both runs' MDEs and both n are
    kept in the output so a reader who wants the stricter reading can take the maximum.
    """
    left_mde, right_mde = left.get("mde"), right.get("mde")
    if not isinstance(left_mde, (int, float)) or not isinstance(right_mde, (int, float)):
        return None, None
    combined = sqrt((float(left_mde) ** 2 + float(right_mde) ** 2) / 2.0)
    # Which side contributes more of the threshold, for the reader who wants to know whose
    # sample is doing the limiting.
    governed_by = "left" if float(left_mde) >= float(right_mde) else "right"
    return round(min(1.0, combined), 4), governed_by


def _column(run: TargetRun, suite: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": run.label,
        "score": suite.get("score"),
        "ci": suite.get("ci"),
        "n": suite.get("n"),
        "mde": suite.get("mde"),
        "floor": suite.get("floor"),
        "verdict": suite.get("verdict"),
        "hard_failures": suite.get("hard_failures") or [],
    }


def _pairs(runs: list[TargetRun], suites: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every ordered pair, in the order the targets were given. No ranking."""
    out: list[dict[str, Any]] = []
    present = [run for run in runs if run.label in suites]
    for i, left in enumerate(present):
        for right in present[i + 1:]:
            left_suite, right_suite = suites[left.label], suites[right.label]
            left_score, right_score = left_suite.get("score"), right_suite.get("score")
            if not isinstance(left_score, (int, float)) or \
                    not isinstance(right_score, (int, float)):
                # One side has no score. Subtracting it would either crash or, worse,
                # coerce the absence to zero and publish "no difference".
                missing = [
                    run.label for run, score in ((left, left_score), (right, right_score))
                    if not isinstance(score, (int, float))
                ]
                out.append({
                    "left": left.label,
                    "right": right.label,
                    "left_score": left_score,
                    "right_score": right_score,
                    "delta": None,
                    "left_mde": left_suite.get("mde"),
                    "right_mde": right_suite.get("mde"),
                    "left_n": left_suite.get("n"),
                    "right_n": right_suite.get("n"),
                    "mde": None,
                    "label": NOT_COMPARABLE,
                    "note": (
                        f"no score to compare: {', '.join(missing)} recorded none for this "
                        f"suite, and an absent measurement is not a difference of zero"
                    ),
                })
                continue
            delta = round(float(right_score) - float(left_score), 4)
            mde, governed_by = _governing_mde(left_suite, right_suite)
            entry: dict[str, Any] = {
                "left": left.label,
                "right": right.label,
                "left_score": left_score,
                "right_score": right_score,
                "delta": delta,
                "left_mde": left_suite.get("mde"),
                "right_mde": right_suite.get("mde"),
                "left_n": left_suite.get("n"),
                "right_n": right_suite.get("n"),
                "mde": mde,
            }
            if mde is None:
                entry["label"] = NOT_QUALIFIABLE
                entry["note"] = (
                    "at least one of these runs reports no minimum detectable effect for this "
                    "suite, so nothing here can say whether this difference is real"
                )
            elif abs(delta) >= mde:
                entry["label"] = DISTINGUISHABLE
                entry["governing_mde_from"] = (
                    left.label if governed_by == "left" else right.label
                )
                entry["note"] = (
                    f"the difference is at least the threshold these two samples can "
                    f"distinguish ({mde})"
                )
            else:
                entry["label"] = INSIDE_NOISE
                entry["governing_mde_from"] = (
                    left.label if governed_by == "left" else right.label
                )
                entry["note"] = (
                    f"the difference is smaller than the threshold these two samples can "
                    f"distinguish ({mde}); these are the same score at this sample size"
                )
            out.append(entry)
    return out


def _unit_differences(runs: list[TargetRun], suites: dict[str, dict[str, Any]]
                      ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Units the targets scored differently, and units they did not all score.

    Kept apart on purpose. A unit one target scored and another did not is missing coverage,
    not a disagreement about the answer, and folding the two together would report an absent
    measurement as a difference of opinion.
    """
    present = [run for run in runs if run.label in suites]
    tables = {run.label: _units(suites[run.label]) for run in present}
    every_key = sorted({key for table in tables.values() for key in table})

    disagreements: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for key in every_key:
        scored_by = [run.label for run in present if key in tables[run.label]]
        if len(scored_by) != len(present):
            coverage.append({
                "unit": key,
                "scored_by": scored_by,
                "not_scored_by": [run.label for run in present
                                  if key not in tables[run.label]],
            })
            continue
        scores = {run.label: tables[run.label][key].get("score") for run in present}
        verdicts = {run.label: tables[run.label][key].get("verdict") for run in present}
        numeric = [v for v in scores.values() if isinstance(v, (int, float))]
        if len(numeric) != len(present):
            # One target could score this unit and another reported it UNVERIFIABLE. That is a
            # difference worth seeing, and it is not a difference of degree.
            disagreements.append({
                "unit": key,
                "scores": scores,
                "verdicts": verdicts,
                "kind": "one target did not score this unit",
            })
            continue
        if len(set(numeric)) > 1:
            disagreements.append({
                "unit": key,
                "scores": scores,
                "verdicts": verdicts,
                "kind": "scored differently",
            })
    return disagreements, coverage


def compare_runs(runs: list[TargetRun]) -> dict[str, Any]:
    """One comparison over several finished audits of the same evidence.

    Raises `CompareError` when the runs are not comparable. The refusal is not a section of
    the output: a document that both refuses and tabulates would be read from the table.
    """
    reasons = refusals(runs)
    if reasons:
        raise CompareError(
            "these targets were not audited against the same evidence, so their scores are "
            "not comparable:\n  - " + "\n  - ".join(reasons)
        )
    head = _provenance(runs[0])
    by_suite: dict[str, dict[str, dict[str, Any]]] = {}
    for run in runs:
        for suite in run.report.get("suites", []):
            by_suite.setdefault(str(suite["suite"]), {})[run.label] = suite

    suites_out: list[dict[str, Any]] = []
    for suite_id in sorted(by_suite):
        suites = by_suite[suite_id]
        scored_by = [run.label for run in runs if run.label in suites]
        not_scored_by = [run.label for run in runs if run.label not in suites]
        disagreements, coverage = _unit_differences(runs, suites)
        entry: dict[str, Any] = {
            "suite": suite_id,
            "scored_by": scored_by,
            "not_scored_by": not_scored_by,
            "columns": [_column(run, suites[run.label]) for run in runs
                        if run.label in suites],
            # `_pairs` only pairs targets that scored this suite, so no pair ever spans an
            # absence. The targets that did not score it are named in `not_scored_by` and are
            # never given a delta of zero against the ones that did.
            "pairs": _pairs(runs, suites),
            "unit_disagreements": disagreements,
            "unit_coverage_differences": coverage,
        }
        if not_scored_by:
            entry["note"] = (
                f"not compared: {', '.join(not_scored_by)} did not score this suite, and a "
                f"score compared against no score is not a difference"
            )
        suites_out.append(entry)

    return {
        "format": COMPARISON_FORMAT,
        "format_version": COMPARISON_FORMAT_VERSION,
        # Order given, not order of merit. There is no ranking column and no composite score;
        # see the README's non-goals.
        "targets": [
            {
                "position": run.position,
                "label": run.label,
                "name": run.name,
                "config": run.config,
                "run_id": _provenance(run).get("run_id"),
                "dataset_id": _provenance(run).get("dataset_id"),
                "verdict": run.report.get("verdict"),
            }
            for run in runs
        ],
        # The question set is what these runs share. Each target's dataset hash is listed
        # per target rather than once, because it covers that target's own recorded answers
        # and therefore differs whenever the comparison is worth making at all.
        "evidence": {
            "question_set_sha256": runs[0].question_set_sha256,
            "question_set_id": short_id(runs[0].question_set_sha256),
            "judge_config_sha256": head["judge_config_sha256"],
            "datasets": {run.label: _provenance(run)["dataset_sha256"] for run in runs},
        },
        "caveats": caveats(runs),
        "suites": suites_out,
        # The coupling disclosure is per target: it is computed from that run's own per-item
        # records, and two targets can have different suites failing together.
        "couplings": {run.label: run.report.get("couplings") for run in runs},
        "notes": {
            "mde": "a delta smaller than the suite's minimum detectable effect is the same "
                   "score at this sample size, not a smaller difference",
            "not_qualifiable": "a suite reporting no minimum detectable effect cannot say "
                               "whether a difference is real; that is not the same as saying "
                               "the difference is inside noise",
            "ranking": "targets appear in the order given. There is no ranking column and no "
                       "composite score: this compares suites, it does not choose a winner",
        },
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _delta(value: Any) -> str:
    """A delta, or the absence of one said out loud.

    `None` renders as `no score`, never as `+0.0000`. The whole point of carrying `None`
    through the structure is lost if the document that a person actually reads prints a zero.
    """
    if value is None:
        return "no score"
    return f"{value:+.4f}"


def _ci(ci: dict[str, Any] | None) -> str:
    if not ci:
        return "n/a"
    return f"{ci['lower']:.4f} to {ci['upper']:.4f}"


def render_markdown(comparison: dict[str, Any]) -> str:
    """The comparison as a document. Deterministic: no clock, no set iteration order."""
    out: list[str] = ["# Comparison", ""]
    evidence = comparison["evidence"]
    out += [
        f"{len(comparison['targets'])} targets, one question set "
        f"`{evidence['question_set_id']}`, judge configuration "
        f"`{evidence['judge_config_sha256'][:12]}`. Each target's dataset hash covers its "
        f"own recorded answers and so differs; the questions do not.",
        "",
        "Targets appear in the order given. There is no ranking column and no composite "
        "score.",
        "",
        "| # | Target | Run | Dataset | Verdict | Config |",
        "|---|--------|-----|---------|---------|--------|",
    ]
    for target in comparison["targets"]:
        out.append(
            f"| {target['position']} | {target['name']} | `{target['run_id']}` | "
            f"`{target['dataset_id']}` | **{target['verdict']}** | `{target['config']}` |"
        )
    out.append("")
    if comparison["caveats"]:
        out += ["## Read these first", ""]
        out += [f"- {c}" for c in comparison["caveats"]] + [""]

    for suite in comparison["suites"]:
        out += [f"## {suite['suite']}", ""]
        if suite["not_scored_by"]:
            out += [f"{suite['note']}.", ""]
        out += ["| Target | Score | 95% CI | n | MDE | Floor | Verdict |",
                "|--------|-------|--------|---|-----|-------|---------|"]
        for column in suite["columns"]:
            out.append(
                f"| {column['target']} | {_fmt(column['score'])} | {_ci(column['ci'])} | "
                f"{column['n']} | {_fmt(column['mde'])} | {_fmt(column['floor'])} | "
                f"{column['verdict']} |"
            )
        out.append("")
        if suite["pairs"]:
            out += ["| Pair | Delta | Threshold | Reading |",
                    "|------|-------|-----------|---------|"]
            for pair in suite["pairs"]:
                out.append(
                    f"| {pair['left']} vs {pair['right']} | {_delta(pair['delta'])} | "
                    f"{_fmt(pair['mde'])} | **{pair['label']}** |"
                )
            out.append("")
        if suite["unit_disagreements"]:
            out += [f"Units scored differently ({len(suite['unit_disagreements'])}):", ""]
            for row in suite["unit_disagreements"]:
                scores = ", ".join(f"{k} {_fmt(v)}" for k, v in sorted(row["scores"].items()))
                out.append(f"- `{row['unit']}` -- {row['kind']}: {scores}")
            out.append("")
        if suite["unit_coverage_differences"]:
            out += [
                f"Units one target scored and another did not "
                f"({len(suite['unit_coverage_differences'])}). This is missing coverage, not "
                f"a difference of opinion:",
                "",
            ]
            for row in suite["unit_coverage_differences"]:
                out.append(
                    f"- `{row['unit']}` -- not scored by {', '.join(row['not_scored_by'])}"
                )
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def render_json(comparison: dict[str, Any]) -> str:
    return json.dumps(comparison, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def summarize_for_terminal(comparison: dict[str, Any]) -> list[str]:
    """The short form a person reads in the shell."""
    lines = [
        f"targets: " + ", ".join(t["label"] for t in comparison["targets"]),
        f"evidence: question set {comparison['evidence']['question_set_id']}, "
        f"judge {comparison['evidence']['judge_config_sha256'][:12]}",
    ]
    for suite in comparison["suites"]:
        if suite["not_scored_by"]:
            lines.append(
                f"{suite['suite']}: not scored by "
                f"{', '.join(suite['not_scored_by'])}; no delta is reported against them"
            )
        for pair in suite["pairs"]:
            lines.append(
                f"{suite['suite']}: {pair['left']} vs {pair['right']} "
                f"{_delta(pair['delta'])} -> {pair['label']}"
            )
    return lines
