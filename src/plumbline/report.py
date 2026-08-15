"""Report rendering: machine-readable JSON and human-readable Markdown.

A verdict is a record. Both formats open with the overall verdict and carry
the full provenance block: run id, harness version, seed, dataset hash, judge
configuration hash. Reports contain no wall-clock timestamps — run identity is
content-derived, which is what makes identical re-runs byte-identical; the git
history of the committed report is the time record.
"""

from __future__ import annotations

import json
from pathlib import Path

from .suites import SuiteResult

REPORT_JSON = "report.json"
REPORT_MD = "report.md"


def build_report(
    *,
    verdict: str,
    provenance: dict,
    target: str,
    dataset_info: dict,
    results: list[SuiteResult],
    warnings: list[str],
) -> dict:
    return {
        "verdict": verdict,  # first key, per spec: overall verdict first
        "provenance": provenance,
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
        "warnings": warnings,
        "notes": {
            "mde": "mde is the smallest true drop in a suite's score that a same-sized future run could tell apart from noise; a regression smaller than it would not be detectable at this sample size",
            "hard_failures": "a suite with hard_failures fails regardless of its pooled score: a load-bearing policy fact was wrong, and pooled averages absorb single-item fabrications",
            "reproducibility": "identical inputs and seed produce byte-identical reports; reports carry no timestamps by design",
        },
    }


def _format_ci(ci: dict | None) -> str:
    if not ci:
        return "n/a"
    return f"{ci['lower']:.4f} – {ci['upper']:.4f}"


def _format_mde(mde: float | None) -> str:
    return "n/a" if mde is None else f"{mde:.4f}"


def render_markdown(report: dict) -> str:
    p = report["provenance"]
    lines: list[str] = []
    lines.append(f"# Audit verdict: {report['verdict']}")
    lines.append("")
    lines.append(f"Plumbline audit of target `{report['target']}`.")
    lines.append("")
    lines.append("## Provenance")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Run id | `{p['run_id']}` |")
    lines.append(f"| Harness version | `{p['harness_version']}` |")
    lines.append(f"| Seed | `{p['seed']}` |")
    lines.append(f"| Dataset hash | `{p['dataset_sha256']}` (short: `{p['dataset_id']}`) |")
    lines.append(f"| Judge | `{p['judge_kind']}`, config hash `{p['judge_config_sha256']}` |")
    lines.append("")
    ds = report["dataset"]
    synthetic = " **(synthetic demonstration data — not a benchmark)**" if ds.get("synthetic") else ""
    lines.append(f"Dataset: `{ds['name']}`, {ds['items']} items.{synthetic}")
    lines.append("")
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
    for s in report["suites"]:
        reason = (s.get("stats") or {}).get("reason")
        if reason and s["ci"] is None:
            lines.append(f"- `{s['suite']}` reports no interval: {reason}.")
    if any((s.get("stats") or {}).get("reason") for s in report["suites"]
           if s["ci"] is None):
        lines.append("")
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
    """
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
