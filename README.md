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

Pre-release (`0.1.0.dev0`). Built from a functional
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

# 4. Second run: three independent checks catch the planted fact, exit code 1.
PYTHONPATH=src python3 -m plumbline audit --config examples/riverbend.toml --out audits
echo $?   # 1

# 5. Restore the demo bundle.
git checkout -- datasets/riverbend-demo
```

Three suites catch it on the second run, and two of them are above their
floors when they do:

| Suite | Score | Floor | Verdict | Why |
|---|---|---|---|---|
| `accuracy` | 0.8680 | 0.75 | **FAIL** | the planted number is on a load-bearing item |
| `groundedness` | 0.8166 | 0.70 | **FAIL** | 900 appears in no source |
| `cross_language` | 0.6250 | 1.00 | **FAIL** | English now says 900, Spanish still says 850 |

That is the whole argument for the design. A pooled average absorbs one
fabricated fact — both `accuracy` and `groundedness` are comfortably over
their floors and fail on severity, not on score. And the same fact asked in
two languages cannot be quietly wrong in one of them.

## What is implemented

- Evidence bundle format v1: versioned dataset with per-item language,
  expected behavior class (answer vs. refusal), translation review status,
  load-bearing flags, cross-language fact links, retrieved source ids; a
  source corpus; recorded responses; SHA-256 integrity manifest.
- Suites: `smoke` (target is testable at all, floor 1.00); `accuracy`
  (token-F1 with a load-bearing per-item override that can fail the suite
  regardless of the pooled average, floor 0.75); `refusal` (both directions,
  floor 0.90); `cross_language` (paired facts must agree across languages on
  their numbers and on whether they refused, floor 1.00); `groundedness`,
  `citation_validity` and `citation_accuracy` (three questions about the same
  answer: is it supported by its sources, do the sources it cites exist, and
  do *those* sources support it); `multilingual` (answered in the language it
  was asked in, floor 0.95); `adversarial` (probes keep their expected
  behavior and emit nothing forbidden, floor 0.90); `fairness` (the score is
  the disparity between the best- and worst-served group, not the average,
  floor 0.85); `representational_harms` and `privacy` (deterministic screens,
  floor 1.00); `accessibility` (five structural checks on a captured
  interface snapshot, with contrast ratios computed here, floor 1.00). Floors
  are per-target configuration; these are demonstration defaults.
- Enabling a suite the bundle cannot exercise is a configuration error, not a
  vacuous pass.
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

The MDE is the figure that keeps a passing report honest. The bundled demo
audit is thirteen suites of PASS, nine of them a perfect 1.0000 — and their
MDEs run from 0.115 to 0.750. The 26-item sample could not rule out a failure
rate of one in nine on its best-powered suite, or three in four on its worst.
A report that only showed the scores would hide that. Suites whose score is
not a sample statistic say so and print `n/a` with the reason, rather than an
interval that looks like evidence. See `DESIGN.md` for the methods and every constant.

## What is not implemented yet (see DESIGN.md roadmap)

Baseline regression comparison; pin-file gate integration for consuming
repos; live-target adapters and optional model-based judges. Every suite in
the specification's taxonomy is implemented.

## Non-goals

Not a leaderboard. Not a general benchmark. Not a red-team service.
