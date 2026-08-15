"""The audit runner: integrity → validation → suites → report.

Order matters and is fail-closed at every step:
1. Judge and suite construction (config errors surface before touching data).
2. Bundle integrity verification (refusal to score on any mismatch).
3. Warnings collection (visible every run, never fatal).
4. Suite evaluation in sorted suite-id order (deterministic).
5. Report build, baseline comparison, write. Overall verdict is FAIL if any
   enabled suite fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import __version__, bundle as bundle_mod
from .baseline import (
    baseline_digest,
    compare as compare_to_baseline,
    load_baseline,
)
from .config import TargetConfig
from .hashing import config_digest, short_id, sha256_text, canonical_json
from .judges import make_judge
from .report import build_report, write_reports
from .stats import compute as compute_statistics
from .suites import FAIL, PASS, SuiteResult, get as get_suite

DEFAULT_SEED = 1729  # Ramanujan's taxicab number: memorable, obviously arbitrary.

RUN_ID_LEN = 16


def attach_statistics(result: SuiteResult, *, seed: int) -> None:
    """Stamp a confidence interval and a minimum detectable effect onto a
    suite result. Derived per suite from the run seed and the suite id, so
    two suites in the same run do not share a bootstrap resampling sequence
    while the whole run stays reproducible from one seed."""
    suite_seed = int(sha256_text(f"{seed}:{result.suite_id}")[:16], 16)
    stats = compute_statistics(
        score_kind=result.score_kind,
        sample=result.sample,
        strata=result.strata,
        seed=suite_seed,
    )
    result.ci = stats.ci
    result.mde = stats.mde
    result.stats_meta = stats.meta


@dataclass
class AuditOutcome:
    verdict: str
    report: dict
    json_path: Path
    md_path: Path
    warnings: list[str]
    comparison: dict | None = None


def compute_run_id(
    *, harness_version: str, seed: int, dataset_sha256: str,
    judge_config_sha256: str, suite_floors: dict[str, float],
    baseline_sha256: str | None = None,
) -> str:
    """Content-derived run identity: identical inputs give the identical run
    id, so identical re-runs write identical bytes to the identical path.

    The baseline is one of those inputs. Comparing against a different bar
    produces a different report, so it must produce a different run id."""
    material = canonical_json({
        "harness_version": harness_version,
        "seed": seed,
        "dataset_sha256": dataset_sha256,
        "judge_config_sha256": judge_config_sha256,
        "suites": sorted(suite_floors.items()),
        "baseline_sha256": baseline_sha256,
    })
    return sha256_text(material)[:RUN_ID_LEN]


def run_audit(config: TargetConfig, *, seed: int = DEFAULT_SEED, out_dir: Path,
              baseline_path: Path | None = None) -> AuditOutcome:
    # 1. Construction first: a misconfigured run should not touch evidence.
    judge = make_judge(config.judge)  # ValueError on unknown kind -> exit 4
    suites = {suite_id: get_suite(suite_id) for suite_id in sorted(config.suites)}

    # A requested comparison that cannot be loaded is an error, not a skipped
    # extra: the run was asked to check against a bar and could not find it.
    chosen_baseline = baseline_path if baseline_path is not None else config.baseline_path
    baseline_record = load_baseline(chosen_baseline) if chosen_baseline else None

    # 2. Integrity, then parse. bundle.load verifies checksums before parsing;
    #    IntegrityError propagates to the CLI as exit 3, nothing scored.
    bundle = bundle_mod.load(config.dataset_path)

    # 3. Warnings: visible on every run, never fatal, never suppressed.
    warnings = bundle.unreviewed_translation_warnings()

    # 4. Evaluate enabled suites, deterministically ordered, and attach
    #    statistics centrally so no suite can ship without a CI and an MDE.
    results: list[SuiteResult] = []
    for suite_id, suite in suites.items():
        result = suite.evaluate(bundle, judge, config.suites[suite_id])
        attach_statistics(result, seed=seed)
        results.append(result)

    verdict = FAIL if any(r.verdict == FAIL for r in results) else PASS

    judge_config = judge.config()
    judge_config_sha256 = config_digest(judge_config)
    run_id = compute_run_id(
        harness_version=__version__,
        seed=seed,
        dataset_sha256=bundle.dataset_sha256,
        judge_config_sha256=judge_config_sha256,
        suite_floors=config.suites,
        baseline_sha256=(baseline_digest(baseline_record)
                         if baseline_record else None),
    )

    provenance = {
        "run_id": run_id,
        "harness": "plumbline",
        "harness_version": __version__,
        "seed": seed,
        "dataset_sha256": bundle.dataset_sha256,
        "dataset_id": bundle.dataset_id,
        "judge_kind": judge_config["kind"],
        "judge_config_sha256": judge_config_sha256,
    }
    dataset_info = {
        "name": bundle.name,
        "version": bundle.manifest.get("version"),
        "synthetic": bool(bundle.manifest.get("synthetic", False)),
        "items": len(bundle.items),
    }

    report = build_report(
        verdict=verdict,
        provenance=provenance,
        target=config.name,
        dataset_info=dataset_info,
        results=results,
        warnings=warnings,
    )
    # 5. Regression comparison, once the report (and its MDEs) exist.
    comparison = compare_to_baseline(report, baseline_record) if baseline_record else None
    report["baseline"] = comparison

    json_path, md_path = write_reports(report, out_dir)
    return AuditOutcome(
        verdict=verdict, report=report,
        json_path=json_path, md_path=md_path, warnings=warnings,
        comparison=comparison,
    )
