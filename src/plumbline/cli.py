"""Command-line interface.

Exit codes (see DESIGN.md):
  0  all enabled suites passed
  1  scoring completed; at least one suite failed (overall FAIL)
  2  command-line usage error (argparse convention)
  3  integrity refusal: checksum mismatch or missing manifest; nothing scored
  4  configuration / environment error (malformed config, unknown or
     unimplemented suite, unreadable bundle)
  5  internal error: the harness itself failed. Distinct from 1 on purpose —
     exit 1 is a measurement, and a crash is the absence of one. A caller that
     could not tell them apart would read "plumbline fell over" as "plumbline
     scored this target and it failed", which is a verdict nobody produced.

Every non-zero code blocks: there is no code that means "could not check,
carry on".
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from . import __version__
from .audit import (
    CoverageError,
    DEFAULT_SEED,
    ResultError,
    run_audit,
    verify_run_id,
)
from .baseline import (
    BaselineError,
    build_baseline,
    summarize_for_terminal,
    write_baseline,
)
from .bundle import (
    BundleError,
    IntegrityError,
    load_questions as load_bundle_questions,
    seal as seal_bundle,
)
from .config import ConfigError, load_config
from .couplings import summarize_for_terminal as summarize_couplings
from .errors import OutboundError
from .report import ReportSealError, verify_report
from .suites import EmptyPopulationError

EXIT_PASS = 0
EXIT_SUITE_FAILURE = 1
EXIT_USAGE = 2
EXIT_INTEGRITY_REFUSAL = 3
EXIT_CONFIG_ERROR = 4
EXIT_INTERNAL_ERROR = 5


def _warn(lines: list[str]) -> None:
    for line in lines:
        print(f"WARNING: {line}", file=sys.stderr)


def cmd_validate(args: argparse.Namespace) -> int:
    """Inspect a bundle. Accepts a question set too — you should be able to
    check what you are about to send to a live target before you send it, and
    integrity, item count and the translation warnings do not need responses
    to be meaningful. Whether responses are present is reported either way,
    because a bundle with none cannot be scored."""
    bundle = load_bundle_questions(Path(args.bundle))
    langs: dict[str, int] = {}
    for item in bundle.items:
        langs[item.lang] = langs.get(item.lang, 0) + 1
    print(f"bundle:   {bundle.name} (version {bundle.manifest.get('version')})")
    print(f"items:    {len(bundle.items)} "
          f"({', '.join(f'{k}: {v}' for k, v in sorted(langs.items()))})")
    missing = [i.id for i in bundle.items if not bundle.response_for(i.id)]
    if not bundle.manifest.get("files", {}).get("responses"):
        print("responses: none — this is a question set, not gradable "
              "evidence. Record against it with `plumbline record`.")
    elif missing:
        print(f"responses: {len(bundle.responses)} of {len(bundle.items)} "
              f"({len(missing)} empty or absent: {', '.join(missing[:5])}"
              f"{'…' if len(missing) > 5 else ''}); the smoke suite fails on "
              f"these")
    else:
        print(f"responses: {len(bundle.responses)}, one per item")
    print(f"dataset:  {bundle.dataset_id} (sha256 {bundle.dataset_sha256})")
    if bundle.manifest.get("synthetic"):
        print("note:     synthetic demonstration data — not a benchmark")
    recording = bundle.manifest.get("recording")
    if recording:
        adapter = recording.get("adapter") or {}
        print(f"recorded: {recording.get('recorded_at')} from "
              f"{adapter.get('endpoint')} via the {adapter.get('kind')} adapter")
    _warn(bundle.unreviewed_translation_warnings())
    print("integrity: OK")
    return EXIT_PASS


def cmd_seal(args: argparse.Namespace) -> int:
    checksums = seal_bundle(Path(args.bundle))
    print(f"sealed:  {args.bundle}")
    print(f"dataset: {checksums['bundle_sha256'][:12]} (sha256 {checksums['bundle_sha256']})")
    print("note:    the bundle hash changed if any evidence changed; that trace is the point")
    return EXIT_PASS


def _read_report(source: Path) -> dict:
    try:
        with open(source, encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise BaselineError(f"unreadable report {source}: {e}") from e
    if not isinstance(report, dict) or "provenance" not in report \
            or "suites" not in report:
        raise BaselineError(f"{source} is not a Plumbline report")
    return report


def cmd_verify(args: argparse.Namespace) -> int:
    """Check a written report against its own seal.

    A seal nobody checks is decoration, so it gets a command. This is what a
    reviewer runs on the report.json in a pull request before believing the
    verdict at the top of it.
    """
    source = Path(args.report)
    report = _read_report(source)
    digest = verify_report(report, source=str(source))
    run_id = verify_run_id(report, source=str(source))
    provenance = report["provenance"]
    print(f"report:  {source}")
    print(f"verdict: {report['verdict']}")
    print(f"target:  {report.get('target')}")
    print(f"run:     {run_id} — derived from this report's own inputs")
    print(f"seal:    {digest} — matches the report's contents")
    print(f"dataset: {provenance['dataset_sha256']}")
    print("note:    this is tamper evidence, not authentication. The seal is a "
          "plain sha256 with no secret in it, so anyone who can edit the file "
          "can recompute it; what it proves is that the copy in front of you "
          "is the copy that was written, which is what catches an edit in "
          "review, in a diff, or in transit. Vouching for WHO produced a "
          "report needs a signature over these bytes, which Plumbline does not "
          "issue.")
    print("note:    the seal covers this report's body. It does not vouch for "
          "the evidence beyond the dataset hash above; verify that bundle with "
          "`plumbline validate`.")
    return EXIT_PASS


def cmd_baseline(args: argparse.Namespace) -> int:
    """Distil a finished report into the record a repository commits as its
    bar for future runs."""
    source = Path(args.source)
    report = _read_report(source)
    # A baseline is the bar every later run is judged against, so it may only
    # be cut from a report that still matches its own seal, and whose run id is
    # the one its contents generate. Distilling an edited report would launder
    # a hand-written number — or a borrowed run id — into the thing the
    # repository treats as ground truth.
    verify_report(report, source=str(source))
    verify_run_id(report, source=str(source))
    record = build_baseline(report)
    out = write_baseline(record, Path(args.out))
    print(f"baseline: {out}")
    print(f"from run: {record['source_run_id']} (verdict {record['verdict']})")
    print(f"dataset:  {record['dataset_id']}")
    print(f"judge:    {record['judge_config_sha256'][:12]}")
    print("note:     comparison against this baseline is refused if either "
          "hash changes")
    return EXIT_PASS


def cmd_record(args: argparse.Namespace) -> int:
    """Ask a live target every question in a question set and write a new,
    sealed evidence bundle. The only command in Plumbline that opens a socket;
    `audit` and `gate` grade what this leaves behind."""
    from .adapters import make_adapter          # imported here, and only here,
    from .recording import record               # so the gate path never can

    config = load_config(Path(args.config))
    adapter, adapter_warnings = make_adapter(config.adapter)
    _warn(adapter_warnings)

    # One config, both commands: by default the recording is written where
    # `[dataset].path` says the graded bundle lives, and the question set is
    # whatever `[adapter].questions` names. Recording into the question set is
    # refused, so a config that sets neither gets a legible error rather than
    # a bundle that overwrote its own questions.
    questions_path = (Path(args.questions) if args.questions
                      else config.questions_path or config.dataset_path)
    out_dir = Path(args.out) if args.out else config.dataset_path
    questions = load_bundle_questions(questions_path)
    _warn(questions.unreviewed_translation_warnings())

    print(f"target:    {config.name}")
    print(f"adapter:   {adapter.kind} -> {adapter.describe()['endpoint']}")
    print(f"questions: {questions.name} ({len(questions.items)} items, "
          f"dataset {questions.dataset_id})")

    result = record(questions=questions, adapter=adapter,
                    out_dir=out_dir, overwrite=args.overwrite,
                    synthetic=args.synthetic, note=args.note)

    print(f"recorded:  {result.recorded} responses")
    if result.empty:
        _warn([f"item {e['id']} recorded an empty response: {e['error']}"
               for e in result.empty])
        print(f"empty:     {len(result.empty)} "
              f"(the smoke suite fails on these; nothing was skipped)")
    print(f"bundle:    {result.out_dir}")
    print(f"dataset:   {result.dataset_id} (sha256 {result.dataset_sha256})")
    print(f"recorded at {result.manifest['recording']['recorded_at']}; audit "
          f"this bundle with `plumbline audit`")
    print("note:      its dataset hash is new, so comparison against a "
          "baseline built from other evidence will be refused, as it should be")
    return EXIT_PASS


def _audit_from_args(args: argparse.Namespace, *, offline_only: bool = False):
    config = load_config(Path(args.config))
    baseline_path = Path(args.baseline) if args.baseline else None
    return run_audit(config, seed=args.seed, out_dir=Path(args.out),
                     baseline_path=baseline_path, offline_only=offline_only)


def _suite_lines(report: dict) -> list[str]:
    lines = []
    for s in report["suites"]:
        ci = ("ci n/a" if s["ci"] is None
              else f"ci {s['ci']['lower']:.3f}-{s['ci']['upper']:.3f}")
        mde = "mde n/a" if s["mde"] is None else f"mde {s['mde']:.3f}"
        severity = "  !load-bearing" if s.get("hard_failures") else ""
        block = (s.get("details") or {}).get("unverifiable") or {}
        unverifiable = (f"  {block['count']} unverifiable"
                        if block.get("count") else "")
        lines.append(
            f"  {s['suite']:<22} score {s['score']:.4f}  floor {s['floor']:.2f}  "
            f"{s['verdict']:<4}  n={s['n']:<3} {ci}  {mde}"
            f"{unverifiable}{severity}")
    return lines


def _coupling_lines(report: dict) -> list[str]:
    """Say it in the build log too. Three red suites should not send somebody
    chasing three bugs when the matrix already established they are one."""
    return summarize_couplings(report.get("couplings") or {})


def _judge_line(report: dict) -> str:
    """One line naming the instrument. A model judge says so here too, not
    only in the report file somebody may never open."""
    judge = report.get("judge") or {}
    kind = judge.get("kind", "lexical")
    if judge.get("deterministic", True):
        return f"{kind} (deterministic)"
    return (f"{kind} NOT DETERMINISTIC — model {judge.get('model')}, "
            f"mode {judge.get('mode')}")


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
    print(f"judge:   {_judge_line(outcome.report)}")
    for line in _suite_lines(outcome.report):
        print(line)
    for line in _coupling_lines(outcome.report):
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
    # offline_only: the gate refuses a model judge in live mode. Everything
    # else about the run is identical to `audit`.
    outcome = _audit_from_args(args, offline_only=True)
    report = outcome.report
    print(f"GATE: {report['verdict']} — target {report['target']}, "
          f"dataset {report['provenance']['dataset_id']}, "
          f"run {report['provenance']['run_id']}")
    print(f"judge: {_judge_line(report)}")
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
    for line in _coupling_lines(report):
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

    p_verify = sub.add_parser(
        "verify",
        help="check a written report against its own seal: refuse if the "
             "report was edited after it was produced")
    p_verify.add_argument("report", help="path to a report.json")
    p_verify.set_defaults(func=cmd_verify)

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

    p_record = sub.add_parser(
        "record",
        help="ask a live target every question in a question set and write a "
             "new sealed evidence bundle (the only command that uses the "
             "network)")
    p_record.add_argument("--config", required=True,
                          help="target configuration (TOML) with an [adapter] table")
    p_record.add_argument("--out",
                          help="directory to write the recorded bundle to; "
                               "defaults to [dataset].path, so `record` and "
                               "`audit` can share one config file")
    p_record.add_argument("--questions",
                          help="question set to record against; defaults to "
                               "[adapter].questions, then [dataset].path")
    p_record.add_argument("--overwrite", action="store_true",
                          help="replace an existing recording at --out")
    p_record.add_argument(
        "--synthetic", action="store_true",
        help="mark the recorded bundle synthetic: the target was a fixture or "
             "a demonstration, not a real service")
    p_record.add_argument("--note",
                          help="a line recorded in the bundle manifest saying "
                               "what this recording was for")
    p_record.set_defaults(func=cmd_record)

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
    except ReportSealError as e:
        print(f"INTEGRITY REFUSAL: {e}", file=sys.stderr)
        return EXIT_INTEGRITY_REFUSAL
    except ResultError as e:
        # The instrument malfunctioned. Not exit 1: nothing was measured.
        print(f"INTERNAL ERROR: {e}", file=sys.stderr)
        print("The harness produced a result it cannot honestly aggregate, so "
              "it refused to publish a verdict. This is a bug in Plumbline or "
              "in a suite; please report it.", file=sys.stderr)
        return EXIT_INTERNAL_ERROR
    except (ConfigError, BundleError, BaselineError, EmptyPopulationError,
            CoverageError, OutboundError, ValueError, KeyError) as e:
        msg = e.args[0] if e.args else e
        print(f"CONFIGURATION ERROR: {msg}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except Exception:
        # An unhandled exception used to leave the interpreter, which exits 1 —
        # the code reserved for "scoring completed and something failed". A
        # caller cannot tell those apart, so a crashed harness looked exactly
        # like a graded target. It gets its own code, and the traceback still
        # goes to stderr so the bug is not swallowed either.
        print("INTERNAL ERROR: the harness crashed. Nothing was scored, and "
              "no verdict was produced — this is not a measured failure.",
              file=sys.stderr)
        traceback.print_exc()
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":
    sys.exit(main())
