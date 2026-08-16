"""Report rendering: machine-readable JSON and human-readable Markdown.

A verdict is a record. Both formats open with the overall verdict and carry
the full provenance block: run id, harness version, seed, dataset hash, judge
configuration hash. Reports contain no wall-clock timestamps — run identity is
content-derived, which is what makes identical re-runs byte-identical; the git
history of the committed report is the time record.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .baseline import render_markdown as render_baseline_markdown
from .couplings import render_markdown as render_couplings_markdown
from .hashing import canonical_json, sha256_text
from .suites import SuiteResult

REPORT_JSON = "report.json"
REPORT_MD = "report.md"

# The field inside `provenance` that binds the stamp to the body it stamps.
REPORT_SEAL_FIELD = "report_sha256"


class ReportSealError(Exception):
    """A report's contents do not match its own seal (integrity refusal)."""


def report_digest(report: dict) -> str:
    """sha256 over the report's canonical JSON, with the seal field removed.

    Provenance used to describe the *inputs* to a run — evidence hash, judge
    hash, seed — and nothing tied it to the *output*. So the run id, the
    dataset hash and the judge hash all stayed valid while a score, a verdict
    or a whole suite row was edited underneath them: a reader checking the
    provenance block found everything in order, because everything in it was
    still true. This covers the body, which is what somebody actually reads.
    """
    body = copy.deepcopy(report)
    provenance = body.get("provenance")
    if isinstance(provenance, dict):
        provenance.pop(REPORT_SEAL_FIELD, None)
    return sha256_text(canonical_json(body))


def seal_report(report: dict) -> dict:
    """Stamp a finished report with the digest of its own body, in place."""
    report["provenance"][REPORT_SEAL_FIELD] = report_digest(report)
    return report


def verify_report(report: dict, *, source: str = "report") -> str:
    """Recompute a report's seal and refuse if the body has moved."""
    recorded = (report.get("provenance") or {}).get(REPORT_SEAL_FIELD)
    if not recorded:
        raise ReportSealError(
            f"{source} carries no {REPORT_SEAL_FIELD}, so nothing binds its "
            f"provenance to its contents. Reports written by this version are "
            f"sealed; re-run the audit that produced it."
        )
    actual = report_digest(report)
    if recorded != actual:
        raise ReportSealError(
            f"{source} does not match its own seal: it records "
            f"{recorded[:12]} but its contents hash to {actual[:12]}. The "
            f"report was edited after it was written. Re-run the audit; a "
            f"verdict is a record, not a draft."
        )
    return actual


def build_report(
    *,
    verdict: str,
    provenance: dict,
    judge: dict,
    target: str,
    dataset_info: dict,
    results: list[SuiteResult],
    warnings: list[str],
    couplings: dict | None = None,
) -> dict:
    return {
        "verdict": verdict,  # first key, per spec: overall verdict first
        "provenance": provenance,
        # What instrument produced these scores, in the reader's terms rather
        # than as a hash. `deterministic: false` is the machine-readable form
        # of the banner the Markdown report prints under its title.
        "judge": judge,
        "target": target,
        "dataset": dataset_info,
        "suites": [
            {
                "suite": r.suite_id,
                "score": round(r.score, 4),
                "floor": r.floor,
                "verdict": r.verdict,
                "n": r.n,
                "ci": r.ci,
                "mde": r.mde,
                "hard_failures": r.hard_failures,
                "stats": r.stats_meta,
                "details": r.details,
                "items": r.item_records,
            }
            for r in results
        ],
        # Which enabled suites are not independent signals, and what that
        # means for this run's failures. A reader counting red rows would
        # otherwise count one finding several times.
        "couplings": couplings,
        "warnings": warnings,
        # Filled in by the audit runner after the suites are scored, because a
        # comparison needs the finished report (its MDEs in particular).
        "baseline": None,
        "notes": {
            "mde": "mde is the smallest true drop in a suite's score that a same-sized future run could tell apart from noise; a regression smaller than it would not be detectable at this sample size",
            "hard_failures": "a suite with hard_failures fails regardless of its pooled score: a load-bearing policy fact was wrong, and pooled averages absorb single-item fabrications",
            "reproducibility": "identical inputs and seed produce byte-identical reports; reports carry no timestamps by design",
            "couplings": "suites that read the same evidence are not independent signals; where two of them failed, the couplings block says whether that is one finding or two",
        },
    }


def _format_ci(ci: dict | None) -> str:
    if not ci:
        return "n/a"
    return f"{ci['lower']:.4f} – {ci['upper']:.4f}"


def _format_mde(mde: float | None) -> str:
    return "n/a" if mde is None else f"{mde:.4f}"


def _recording_lines(recording: dict | None) -> list[str]:
    """Where the graded answers came from, when the bundle records it.

    A hand-written transcript and a transcript captured from a production
    service last Tuesday are different kinds of evidence, and a reader
    defending this report needs to know which one they are holding.
    """
    if not recording:
        return []
    adapter = recording.get("adapter") or {}
    questions = recording.get("questions") or {}
    lines = [
        f"Responses were **recorded from a live target** at "
        f"`{recording.get('recorded_at')}` by the "
        f"`{adapter.get('kind')}` adapter against "
        f"`{adapter.get('endpoint')}`, from question set "
        f"`{questions.get('name')}` (`{str(questions.get('sha256', ''))[:12]}`).",
        "",
    ]
    empty = recording.get("responses_recorded_empty") or []
    if empty:
        lines.append(
            f"{len(empty)} response(s) were recorded empty because the call "
            f"failed: {', '.join(e['id'] for e in empty)}. The smoke suite "
            f"scores those as untestable rather than as wrong answers."
        )
        lines.append("")
    if recording.get("note"):
        lines.append(f"Recording note: {recording['note']}")
        lines.append("")
    return lines


def _unverifiable_lines(report: dict) -> list[str]:
    """What each suite could not check, and how much of its population that
    was.

    A suite that quietly narrowed its own population reads exactly like a
    suite that checked everything. Any suite whose details carry the standard
    `unverifiable` block gets a coverage sentence here, whatever it measures.
    """
    lines: list[str] = []
    for s in report["suites"]:
        block = (s.get("details") or {}).get("unverifiable")
        if not block or not block.get("count"):
            continue
        reasons = ", ".join(f"{reason} {len(ids)}"
                            for reason, ids in block["reasons"].items())
        lines.append(
            f"- `{s['suite']}` scored **{block['scored']} of "
            f"{block['eligible']}** eligible items. {block['count']} are "
            f"**UNVERIFIABLE** ({reasons}) — excluded from the score, and not "
            f"counted as passes."
        )
    if lines:
        lines.append("")
    return lines


def render_markdown(report: dict) -> str:
    p = report["provenance"]
    lines: list[str] = []
    lines.append(f"# Audit verdict: {report['verdict']}")
    lines.append("")
    # A non-deterministic judge announces itself above everything else except
    # the verdict. A reader should never have to reach the provenance table to
    # discover that a model produced the scores.
    judge = report.get("judge") or {}
    if judge.get("notice"):
        lines.append(f"> **Scored by a model judge.** {judge['notice']}")
        lines.append("")
    lines.append(f"Plumbline audit of target `{report['target']}`.")
    lines.append("")
    lines.append("## Provenance")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Run id | `{p['run_id']}` |")
    lines.append(f"| Harness version | `{p['harness_version']}` |")
    lines.append(f"| Harness source | "
                 + (f"`{p['harness_source_sha256']}`"
                    if p.get("harness_source_sha256")
                    else f"_{p.get('harness_source_note', 'unavailable')}_")
                 + " |")
    if p.get(REPORT_SEAL_FIELD):
        lines.append(f"| Report seal | `{p[REPORT_SEAL_FIELD]}` "
                     f"(sha256 of this report's own body; check it with "
                     f"`plumbline verify`) |")
    lines.append(f"| Seed | `{p['seed']}` |")
    lines.append(f"| Dataset hash | `{p['dataset_sha256']}` (short: `{p['dataset_id']}`) |")
    determinism = ("deterministic" if judge.get("deterministic", True)
                   else "**not deterministic**")
    lines.append(f"| Judge | `{p['judge_kind']}` ({determinism}), config hash "
                 f"`{p['judge_config_sha256']}` |")
    languages = judge.get("languages")
    if languages:
        lines.append(f"| Language profiles | {', '.join(f'`{t}`' for t in languages)} |")
    lines.append("")
    ds = report["dataset"]
    synthetic = " **(synthetic demonstration data — not a benchmark)**" if ds.get("synthetic") else ""
    lines.append(f"Dataset: `{ds['name']}`, {ds['items']} items.{synthetic}")
    lines.append("")
    lines.extend(_recording_lines(ds.get("recording")))
    lines.append("## Suites")
    lines.append("")
    lines.append("| Suite | Score | Floor | Verdict | n | 95% CI | MDE |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in report["suites"]:
        lines.append(
            f"| {s['suite']} | {s['score']:.4f} | {s['floor']:.2f} | "
            f"**{s['verdict']}**{' !' if s.get('hard_failures') else ''} | "
            f"{s['n']} | {_format_ci(s['ci'])} | {_format_mde(s['mde'])} |"
        )
    lines.append("")
    lines.append("Overall verdict fails if any enabled suite fails.")
    lines.append("")
    lines.append(
        "**MDE** is the smallest true drop in a score that a same-sized future "
        "run could tell apart from noise (95% confidence, 80% power). A "
        "regression smaller than a suite's MDE would not be detectable at this "
        "sample size, whatever the score says."
    )
    lines.append("")
    hard = [s for s in report["suites"] if s.get("hard_failures")]
    if hard:
        lines.append(
            "`!` marks a suite failed by a load-bearing item rather than by its "
            "pooled score:"
        )
        for s in hard:
            lines.append(f"- `{s['suite']}`: {', '.join(s['hard_failures'])}")
        lines.append("")
    lines.extend(_unverifiable_lines(report))
    for s in report["suites"]:
        reason = (s.get("stats") or {}).get("reason")
        if reason and s["ci"] is None:
            lines.append(f"- `{s['suite']}` reports no interval: {reason}.")
    if any((s.get("stats") or {}).get("reason") for s in report["suites"]
           if s["ci"] is None):
        lines.append("")
    if report.get("couplings"):
        lines.extend(render_couplings_markdown(report["couplings"]))
    if report.get("baseline"):
        lines.extend(render_baseline_markdown(report["baseline"]))
    lines.append("## Warnings")
    lines.append("")
    if report["warnings"]:
        for w in report["warnings"]:
            lines.append(f"- WARNING: {w}")
    else:
        lines.append("None.")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for key, note in report["notes"].items():
        lines.append(f"- **{key}**: {note}")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict, out_dir: Path) -> tuple[Path, Path]:
    """Write report.json and report.md under <out_dir>/<run_id>/.

    Deterministic bytes: fixed key order (insertion order of build_report),
    indent=2, ensure_ascii=False, trailing newline.

    Sealing happens here, at the single point every written report passes
    through, so no caller can produce an unsealed one by forgetting.
    """
    seal_report(report)
    run_dir = Path(out_dir) / report["provenance"]["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / REPORT_JSON
    md_path = run_dir / REPORT_MD
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    return json_path, md_path
