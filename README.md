# Plumbline

**The bundled dataset is a demonstration of the instrument, not a benchmark.**
Everything under `datasets/` is small, synthetic, and hand-written for this
repository — a fictional county, fictional programs, fictional numbers. It
exists so you can watch the harness work; it measures nothing about any real
system, and no score produced from it means anything beyond "the instrument
functions." The harness is the product.

Plumbline is an evaluation harness for government-facing chat systems. It
grades a target against an executable quality bar and produces audit reports a
third party could defend:

- **Fail closed, everywhere.** Tampered evidence: the run refuses to score,
  with its own exit code. Any enabled suite under its floor: overall FAIL.
  Unimplemented suite enabled: configuration error. There is no silent-skip
  path.
- **Deterministic and offline by default.** The default judge is lexical; CI
  needs no keys; identical inputs and seed produce byte-identical reports.
- **A verdict is a record.** Every run writes machine-readable and
  human-readable reports stamped with run id, harness version, seed, dataset
  hash, and judge configuration hash.

## Status

Pre-release (`0.1.0.dev0`), milestone 1 of 5. Built from a functional
specification, started 2026-08-15, implemented with AI agents (Claude Code),
reviewed and directed by a human. See `DESIGN.md` for the architecture, all
recorded design decisions, and the roadmap. License: Apache-2.0.

## Quick start

Python ≥ 3.11, no third-party dependencies. From a clean checkout, offline:

```sh
# The one command: full audit of the bundled synthetic demo.
PYTHONPATH=src python3 -m plumbline audit --config examples/riverbend.toml --out audits

# Inspect a bundle: integrity, item count, dataset id, warnings.
PYTHONPATH=src python3 -m plumbline validate datasets/riverbend-demo

# Run the tests.
PYTHONPATH=src:tests python3 -m unittest discover -s tests
```

(Or `pip install -e .` and use `plumbline …` directly.)

Re-running the audit with identical inputs writes byte-identical reports to
the identical path — reports carry no timestamps by design; git history is the
time record.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All enabled suites passed. |
| 1 | At least one enabled suite failed — overall FAIL. |
| 2 | Command-line usage error. |
| 3 | **Integrity refusal**: evidence checksums missing or mismatched. Nothing was scored. |
| 4 | Configuration error: malformed config, unknown/unimplemented suite, unreadable bundle. |

## The tamper drill (try it)

Evidence bundles are protected by SHA-256 checksums (`checksums.json`).
Editing the evidence and re-running until green is structurally impossible
without leaving a trace:

```sh
# 1. Plant a number the sources do not support.
sed -i '' 's/850 dollars/900 dollars/' datasets/riverbend-demo/responses.jsonl

# 2. First run: integrity refusal, nothing scored, exit code 3.
PYTHONPATH=src python3 -m plumbline audit --config examples/riverbend.toml --out audits
echo $?   # 3

# 3. "Regenerate" legitimately — the hash change is the trace.
PYTHONPATH=src python3 -m plumbline seal datasets/riverbend-demo

# 4. Second run: the planted fact fails its load-bearing check ->
#    accuracy suite FAILs regardless of the pooled average, exit code 1.
PYTHONPATH=src python3 -m plumbline audit --config examples/riverbend.toml --out audits
echo $?   # 1

# 5. Restore the demo bundle.
git checkout -- datasets/riverbend-demo
```

Milestones 2–3 extend this drill: the cross-language suite will catch the
planted fact by en/es disagreement, and the regression block will name the
flipped suite while refusing numeric comparison against a baseline with a
different dataset hash.

## What is implemented (milestone 1)

- Evidence bundle format v1: versioned dataset with per-item language,
  expected behavior class (answer vs. refusal), translation review status,
  load-bearing flags, cross-language fact links; recorded responses; SHA-256
  integrity manifest.
- Suites: `smoke` (target is testable at all, floor 1.00), `accuracy`
  (token-F1 with a load-bearing per-item override that can fail the suite
  regardless of the pooled average, floor 0.75), `refusal` (both directions,
  floor 0.90). Floors are per-target configuration; these are demonstration
  defaults.
- Reports: `report.json` + `report.md`, verdict first, full provenance block,
  byte-reproducible.
- Unreviewed-translation warnings on every run — never fatal, never
  suppressed.
- **Statistical honesty**: every suite reports a 95% confidence interval and a
  minimum detectable effect at the sample size used.

## Statistical honesty

Every suite prints two figures beyond its score:

- a **confidence interval** (Wilson for proportions, percentile bootstrap
  otherwise) at 95%, and
- a **minimum detectable effect (MDE)**: the smallest true drop in the score
  that a same-sized future run could tell apart from noise, at 95% confidence
  and 80% power.

The MDE is the figure that keeps a passing report honest. On the 12-item
synthetic demo, suites scoring a perfect 1.0 report an MDE of **0.25** — the
sample could not rule out a failure rate of one in four. A report that only
showed the score would hide that. Suites whose score is not a sample statistic
say so and print `n/a` with the reason, rather than an interval that looks like
evidence. See `DESIGN.md` for the methods and every constant.

## What is not implemented yet (see DESIGN.md roadmap)

Cross-language agreement, groundedness, and citation suites (M2); baseline
regression comparison and fairness/harms/privacy/adversarial suites (M3);
accessibility checks, live-target adapters, optional model-based judges (M4);
pin-file gate integration for consuming repos (M5). Enabling any skeleton
suite is an error today, not a skip.

## Non-goals

Not a leaderboard. Not a general benchmark. Not a red-team service.
