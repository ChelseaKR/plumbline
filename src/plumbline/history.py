"""Longitudinal run history: an append-only record of finished runs, and a
trend view on top of it.

`baseline.py` already compares one run against exactly one stored bar,
refuses the comparison outright across a changed dataset or judge hash, and
qualifies every surviving delta against that suite's minimum detectable
effect (MDE). That is deliberately conservative and correct for what it
does. It also means a slow drift — a suite creeping downward by less than
one comparison's MDE on each individual run — never accumulates into
anything visible, because every comparison is evaluated against the same
fixed point in isolation.

This module is the direct generalization of that mechanism, not a new
statistical claim: it does not replace the pairwise baseline comparison or
loosen its refusal rules, and it computes no interval or p-value of its own.
It records what each run's own report already said about itself, and
reports one plain, structural fact on top — whether a suite's score declined
on every one of the last N comparable runs — which a reader can verify by
eye against the numbers printed next to it. See
`docs/adr/0001-longitudinal-history-is-observation-not-inference.md` for why
it stops there.

**Why an append-only file, not a directory scan.** Reports carry no
timestamps by design — "a report must be a pure function of its inputs" —
so there is no field in a report that says when it ran relative to another
one. Directory modification times are not evidence; they change on a
checkout, a rebase, or a `touch`. `plumbline history append` fixes the
order the only way this harness fixes anything: by writing it down. The
order entries were appended — visible in the git history of the committed
history file, the same way "the git history of the committed report is the
time record" for a single run — is the timeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .report import verify_report

HISTORY_FORMAT = "plumbline-history"
HISTORY_FORMAT_VERSION = 1

# A trend needs enough runs behind it to mean anything; three points is the
# fewest that can show a direction rather than a single step, which the
# pairwise baseline comparison already covers.
DEFAULT_MIN_STREAK = 3


class HistoryError(Exception):
    """A history file or a report given to it is malformed (configuration
    error)."""


def _suite_summary(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        s["suite"]: {"score": s["score"], "floor": s["floor"], "mde": s["mde"]}
        for s in report.get("suites", [])
    }


def record_from_report(report: dict[str, Any], *, source: str = "report") -> dict[str, Any]:
    """The compact record `history append` stores for one run.

    Refuses a report that does not match its own seal first — the same
    discipline `plumbline baseline` and `plumbline sign` already apply
    before distilling anything from a report: a history built from an
    edited report would let a hand-written trend into a record this module
    treats as ground truth.
    """
    verify_report(report, source=source)
    provenance = report["provenance"]
    return {
        "run_id": provenance["run_id"],
        "target": report.get("target"),
        "verdict": report.get("verdict"),
        "dataset_sha256": provenance.get("dataset_sha256"),
        "dataset_id": provenance.get("dataset_id"),
        "judge_config_sha256": provenance.get("judge_config_sha256"),
        "harness_version": provenance.get("harness_version"),
        "suites": _suite_summary(report),
    }


def load_history(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise HistoryError(f"unreadable history file {path}: {e}") from e
    if not isinstance(data, dict) or data.get("format") != HISTORY_FORMAT:
        raise HistoryError(f"{path} is not a Plumbline history file")
    runs = data.get("runs")
    if not isinstance(runs, list):
        raise HistoryError(f"{path}: 'runs' must be a list")
    return runs


def write_history(runs: list[dict[str, Any]], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"format": HISTORY_FORMAT,
                   "format_version": HISTORY_FORMAT_VERSION,
                   "runs": runs}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def append(report: dict[str, Any], history_path: Path, *, source: str = "report") -> tuple[list[dict[str, Any]], bool]:
    """Append one run's record to a history file. Returns (runs, appended) —
    appended is False when the newest entry already names this run id, so
    re-running `history append` after a byte-identical re-run is a no-op
    rather than a duplicate."""
    runs = load_history(history_path)
    record = record_from_report(report, source=source)
    if runs and runs[-1].get("run_id") == record["run_id"]:
        return runs, False
    runs.append(record)
    write_history(runs, history_path)
    return runs, True


def _comparable_chain(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The trailing run of entries sharing the newest entry's dataset and
    judge configuration hash — the same two fields `baseline.py` refuses to
    compare across, applied to a whole window instead of one pair."""
    if not runs:
        return []
    newest = runs[-1]
    key = (newest.get("dataset_sha256"), newest.get("judge_config_sha256"))
    chain = []
    for record in reversed(runs):
        if (record.get("dataset_sha256"), record.get("judge_config_sha256")) != key:
            break
        chain.append(record)
    chain.reverse()
    return chain


def _is_declining(scores: list[float]) -> bool:
    """Every step non-increasing, and at least one step a real decrease —
    not merely flat. A structural fact about the numbers printed next to it,
    checkable by eye; not a hypothesis test and not a new interval."""
    if len(scores) < 2:
        return False
    non_increasing = all(b <= a for a, b in zip(scores, scores[1:]))
    return non_increasing and scores[-1] < scores[0]


def trends(runs: list[dict[str, Any]], *, min_streak: int = DEFAULT_MIN_STREAK) -> dict[str, Any]:
    """Per-suite trend over the trailing comparable chain.

    `chain_len` is how many runs the trend actually looks back over — always
    report it next to a finding, the same way every suite's MDE is printed
    next to its score, so a reader can see how much evidence a "declining"
    label rests on. A chain shorter than `min_streak` reports no findings
    at all; there is no vacuous trend the way there is no vacuous pass.
    """
    chain = _comparable_chain(runs)
    declining: list[dict[str, Any]] = []
    result: dict[str, object] = {
        "chain_len": len(chain),
        "min_streak": min_streak,
        "run_ids": [r["run_id"] for r in chain],
        "comparable": len(chain) == len(runs),
        "declining": declining,
    }
    if len(chain) < min_streak:
        return result
    window = chain[-min_streak:]
    suite_ids = set.intersection(*(set(r["suites"]) for r in window)) \
        if window else set()
    for suite_id in sorted(suite_ids):
        scores = [r["suites"][suite_id]["score"] for r in window]
        if _is_declining(scores):
            declining.append({
                "suite": suite_id,
                "scores": scores,
                "run_ids": [r["run_id"] for r in window],
                "floor": window[-1]["suites"][suite_id]["floor"],
            })
    return result


def render_terminal(result: dict[str, Any]) -> list[str]:
    lines = [
        f"history: {result['chain_len']} run(s) in the comparable chain "
        f"(same dataset and judge hash as the newest)",
    ]
    if not result["comparable"]:
        lines.append(
            "note:    earlier runs exist outside this chain — a dataset or "
            "judge configuration change broke comparability further back; "
            "only the trailing chain is examined")
    if result["chain_len"] < result["min_streak"]:
        lines.append(
            f"trend:   not enough comparable runs for a {result['min_streak']}"
            f"-run trend yet ({result['chain_len']} available)")
        return lines
    if not result["declining"]:
        lines.append(
            f"trend:   no suite declined on every one of the last "
            f"{result['min_streak']} comparable runs")
        return lines
    for d in result["declining"]:
        scores = " -> ".join(f"{s:.4f}" for s in d["scores"])
        lines.append(
            f"trend:   {d['suite']} declined every run for the last "
            f"{len(d['scores'])}: {scores} (floor {d['floor']:.2f}). No "
            f"single step need exceed that suite's MDE for this to be "
            f"worth a look; this is an observation, not a hypothesis test.")
    return lines
