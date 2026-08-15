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
import sys
from pathlib import Path

from . import __version__
from .audit import DEFAULT_SEED, run_audit
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


def cmd_audit(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    outcome = run_audit(config, seed=args.seed, out_dir=Path(args.out))
    _warn(outcome.warnings)
    print(f"verdict: {outcome.verdict}")
    for s in outcome.report["suites"]:
        ci = ("ci n/a" if s["ci"] is None
              else f"ci {s['ci']['lower']:.3f}-{s['ci']['upper']:.3f}")
        mde = "mde n/a" if s["mde"] is None else f"mde {s['mde']:.3f}"
        severity = "  !load-bearing" if s.get("hard_failures") else ""
        print(f"  {s['suite']:<22} score {s['score']:.4f}  floor {s['floor']:.2f}  "
              f"{s['verdict']:<4}  n={s['n']:<3} {ci}  {mde}{severity}")
    print(f"reports: {outcome.json_path}")
    print(f"         {outcome.md_path}")
    return EXIT_PASS if outcome.verdict == "PASS" else EXIT_SUITE_FAILURE


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
    p_audit.set_defaults(func=cmd_audit)

    return parser


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
    except (ConfigError, BundleError, EmptyPopulationError, ValueError, KeyError) as e:
        msg = e.args[0] if e.args else e
        print(f"CONFIGURATION ERROR: {msg}", file=sys.stderr)
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    sys.exit(main())
