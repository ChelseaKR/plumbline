"""Command-line interface.

Exit codes (see DESIGN.md):
  0  all enabled suites passed
  1  scoring completed; at least one suite failed (overall FAIL)
  2  command-line usage error (argparse convention)
  3  integrity refusal: checksum mismatch or missing manifest; nothing scored
  4  configuration / environment error (malformed config, unknown or
     unimplemented suite, unreadable bundle)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .audit import DEFAULT_SEED, run_audit
from .baseline import (
    BaselineError,
    build_baseline,
    summarize_for_terminal,
    write_baseline,
)
from .bundle import BundleError, IntegrityError, load as load_bundle, seal as seal_bundle
from .config import ConfigError, load_config
from .suites import EmptyPopulationError

EXIT_PASS = 0
EXIT_SUITE_FAILURE = 1
EXIT_USAGE = 2
EXIT_INTEGRITY_REFUSAL = 3
EXIT_CONFIG_ERROR = 4


def _warn(lines: list[str]) -> None:
    for line in lines:
        print(f"WARNING: {line}", file=sys.stderr)


def cmd_validate(args: argparse.Namespace) -> int:
    bundle = load_bundle(Path(args.bundle))
    langs: dict[str, int] = {}
    for item in bundle.items:
        langs[item.lang] = langs.get(item.lang, 0) + 1
    print(f"bundle:   {bundle.name} (version {bundle.manifest.get('version')})")
    print(f"items:    {len(bundle.items)} "
          f"({', '.join(f'{k}: {v}' for k, v in sorted(langs.items()))})")
    print(f"dataset:  {bundle.dataset_id} (sha256 {bundle.dataset_sha256})")
    if bundle.manifest.get("synthetic"):
        print("note:     synthetic demonstration data — not a benchmark")
    _warn(bundle.unreviewed_translation_warnings())
    print("integrity: OK")
    return EXIT_PASS


def cmd_seal(args: argparse.Namespace) -> int:
    checksums = seal_bundle(Path(args.bundle))
    print(f"sealed:  {args.bundle}")
    print(f"dataset: {checksums['bundle_sha256'][:12]} (sha256 {checksums['bundle_sha256']})")
    print("note:    the bundle hash changed if any evidence changed; that trace is the point")
    return EXIT_PASS


def cmd_baseline(args: argparse.Namespace) -> int:
    """Distil a finished report into the record a repository commits as its
    bar for future runs."""
    source = Path(args.source)
    try:
        with open(source, encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise BaselineError(f"unreadable report {source}: {e}") from e
    if "provenance" not in report or "suites" not in report:
        raise BaselineError(f"{source} is not a Plumbline report")
    record = build_baseline(report)
    out = write_baseline(record, Path(args.out))
    print(f"baseline: {out}")
    print(f"from run: {record['source_run_id']} (verdict {record['verdict']})")
    print(f"dataset:  {record['dataset_id']}")
    print(f"judge:    {record['judge_config_sha256'][:12]}")
    print("note:     comparison against this baseline is refused if either "
          "hash changes")
    return EXIT_PASS


def _audit_from_args(args: argparse.Namespace):
    config = load_config(Path(args.config))
    baseline_path = Path(args.baseline) if args.baseline else None
    return run_audit(config, seed=args.seed, out_dir=Path(args.out),
                     baseline_path=baseline_path)


def _suite_lines(report: dict) -> list[str]:
    lines = []
    for s in report["suites"]:
        ci = ("ci n/a" if s["ci"] is None
              else f"ci {s['ci']['lower']:.3f}-{s['ci']['upper']:.3f}")
        mde = "mde n/a" if s["mde"] is None else f"mde {s['mde']:.3f}"
        severity = "  !load-bearing" if s.get("hard_failures") else ""
        lines.append(
            f"  {s['suite']:<22} score {s['score']:.4f}  floor {s['floor']:.2f}  "
            f"{s['verdict']:<4}  n={s['n']:<3} {ci}  {mde}{severity}")
    return lines


def _baseline_exit(outcome, args) -> int | None:
    """The configuration-error code when a strict run got an incomparable
    baseline, otherwise None."""
    if (outcome.comparison and not outcome.comparison["comparable"]
            and args.require_comparable_baseline):
        print("CONFIGURATION ERROR: --require-comparable-baseline was set and "
              "the baseline is not comparable to this run. The audit itself "
              "completed; see the report.", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    return None


def cmd_audit(args: argparse.Namespace) -> int:
    outcome = _audit_from_args(args)
    _warn(outcome.warnings)
    print(f"verdict: {outcome.verdict}")
    for line in _suite_lines(outcome.report):
        print(line)
    if outcome.comparison:
        for line in summarize_for_terminal(outcome.comparison):
            print(line)
    print(f"reports: {outcome.json_path}")
    print(f"         {outcome.md_path}")
    return _baseline_exit(outcome, args) or (
        EXIT_PASS if outcome.verdict == "PASS" else EXIT_SUITE_FAILURE)


def cmd_gate(args: argparse.Namespace) -> int:
    """The CI entry point. Same audit, same exit codes, output shaped for a
    build log: the verdict on the first and last line, and every failing
    suite named in between."""
    outcome = _audit_from_args(args)
    report = outcome.report
    print(f"GATE: {report['verdict']} — target {report['target']}, "
          f"dataset {report['provenance']['dataset_id']}, "
          f"run {report['provenance']['run_id']}")
    _warn(outcome.warnings)

    failed = [s for s in report["suites"] if s["verdict"] != "PASS"]
    if failed:
        print(f"{len(failed)} of {len(report['suites'])} suites failed:")
        for s in failed:
            reason = (f"load-bearing item(s) {', '.join(s['hard_failures'])}"
                      if s.get("hard_failures")
                      else f"score {s['score']:.4f} below floor {s['floor']:.2f}")
            print(f"  {s['suite']}: {reason}")
    else:
        print(f"all {len(report['suites'])} suites passed:")
    for line in _suite_lines(report):
        print(line)
    if outcome.comparison:
        for line in summarize_for_terminal(outcome.comparison):
            print(line)
    print(f"reports: {outcome.json_path}")

    if args.summary_file:
        summary = Path(args.summary_file)
        summary.parent.mkdir(parents=True, exist_ok=True)
        with open(summary, "a", encoding="utf-8") as f:
            f.write(outcome.md_path.read_text(encoding="utf-8"))
            f.write("\n")
        print(f"summary: appended to {summary}")

    strict = _baseline_exit(outcome, args)
    if strict is not None:
        print("GATE: REFUSED (baseline not comparable and comparability was "
              "required)")
        return strict
    if report["verdict"] == "PASS":
        print("GATE: PASS")
        return EXIT_PASS
    print("GATE: FAIL")
    return EXIT_SUITE_FAILURE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plumbline",
        description="Fail-closed, deterministic evaluation harness for "
                    "government-facing chat systems.",
    )
    parser.add_argument("--version", action="version", version=f"plumbline {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="verify bundle integrity and report item count, dataset id, warnings")
    p_validate.add_argument("bundle", help="path to an evidence bundle directory")
    p_validate.set_defaults(func=cmd_validate)

    p_seal = sub.add_parser("seal", help="(re)generate a bundle's checksums.json")
    p_seal.add_argument("bundle", help="path to an evidence bundle directory")
    p_seal.set_defaults(func=cmd_seal)

    p_audit = sub.add_parser("audit", help="run the full audit and write provenance-stamped reports")
    p_audit.add_argument("--config", required=True, help="target configuration (TOML)")
    p_audit.add_argument("--out", default="audits", help="report output directory (default: audits)")
    p_audit.add_argument("--seed", type=int, default=DEFAULT_SEED,
                         help=f"random seed, recorded in provenance (default: {DEFAULT_SEED})")
    _add_baseline_arguments(p_audit)
    p_audit.set_defaults(func=cmd_audit)

    p_gate = sub.add_parser(
        "gate",
        help="CI entry point: run the audit and exit 0 pass / 1 fail / "
             "3 integrity refusal / 4 misconfiguration")
    p_gate.add_argument("--config", required=True, help="target configuration (TOML)")
    p_gate.add_argument("--out", default="audits", help="report output directory (default: audits)")
    p_gate.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"random seed, recorded in provenance (default: {DEFAULT_SEED})")
    p_gate.add_argument("--summary-file",
                        help="append the human-readable report to this file "
                             "(for example \"$GITHUB_STEP_SUMMARY\")")
    _add_baseline_arguments(p_gate)
    p_gate.set_defaults(func=cmd_gate)

    p_baseline = sub.add_parser(
        "baseline",
        help="write the committed baseline record distilled from a report")
    p_baseline.add_argument("--from", dest="source", required=True,
                            help="a report.json produced by `plumbline audit`")
    p_baseline.add_argument("--out", required=True,
                            help="path to write the baseline record to")
    p_baseline.set_defaults(func=cmd_baseline)

    return parser


def _add_baseline_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--baseline",
        help="baseline record to compare this run against; overrides "
             "[baseline].path in the target config")
    parser.add_argument(
        "--require-comparable-baseline", action="store_true",
        help="exit with the configuration-error code if the baseline is not "
             "comparable (differing dataset or judge configuration hash) "
             "instead of only saying so in the report")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except IntegrityError as e:
        print(f"INTEGRITY REFUSAL: {e}", file=sys.stderr)
        print("Nothing was scored. If this change to the evidence is legitimate, "
              "re-seal the bundle with `plumbline seal` — the hash change is the trace.",
              file=sys.stderr)
        return EXIT_INTEGRITY_REFUSAL
    except (ConfigError, BundleError, BaselineError, EmptyPopulationError,
            ValueError, KeyError) as e:
        msg = e.args[0] if e.args else e
        print(f"CONFIGURATION ERROR: {msg}", file=sys.stderr)
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    sys.exit(main())
