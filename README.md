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

Pre-release (`0.1.0.dev0`). Every capability in the functional specification
is implemented: thirteen scoring suites, per-suite confidence intervals and
minimum detectable effect, baseline regression comparison, and a pinned
fail-closed CI gate. 172 tests, standard library only, offline.

Built from a functional specification, started 2026-08-15, implemented with AI
agents (Claude Code), reviewed and directed by a human. `DESIGN.md` carries
the architecture, every design decision the specification left open, and an
acceptance record of commands actually run against a clean checkout. License:
Apache-2.0.

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

## Using it as a CI gate

`plumbline gate` is the entry point built for a build log: the verdict is the
first line and the last line, every failing suite is named with why it failed,
and `--summary-file` appends the human-readable report wherever your CI system
renders one.

```sh
PYTHONPATH=src python3 -m plumbline gate --config examples/riverbend.toml \
  --summary-file "$GITHUB_STEP_SUMMARY"
```

### Exit codes

| Code | Meaning | What CI should do |
|---|---|---|
| 0 | All enabled suites passed | merge |
| 1 | At least one enabled suite failed — overall FAIL | block; read the named suites |
| 2 | Command-line usage error | fix the command |
| 3 | **Integrity refusal**: evidence checksums missing or mismatched, nothing was scored | block; the evidence is untrustworthy, which is a different problem from a regression |
| 4 | Configuration or environment error, including an unresolvable harness | block; the gate did not run |

The separation of 1, 3 and 4 is deliberate. "The target got worse", "the
evidence is untrustworthy" and "the gate was misconfigured" need three
different people to do three different things.

### Pinning the harness in a consuming repository

Copy two files from [`gate/`](gate/) into the repository you want gated: the
runner `plumbline-gate.sh` and a `plumbline.pin`.

```
repo = https://github.com/ChelseaKR/plumbline.git
ref  = <40-character commit hash>
config = plumbline/target.toml
```

Then `./plumbline-gate.sh` is the command, locally and in CI, and both read
that one file. The `ref` must be an exact commit — the runner rejects a branch
or a tag, because a moving ref means a green gate today can quietly mean
something else tomorrow. The harness is fetched at run time and verified to be
at the pinned commit; it is never a dependency in your lockfile, so your own
dependency resolution cannot move the thing auditing you.

If the harness cannot be reached, the job **fails**, with the reason on
stderr. It does not skip and it does not report green. A gate that could not
run is not a gate that passed. See [`gate/README.md`](gate/README.md).

## The tamper drill (try it)

Evidence bundles are protected by SHA-256 checksums (`checksums.json`).
Editing the evidence and re-running until green is structurally impossible
without leaving a trace:

```sh
# 1. Plant a number the sources do not support.
python3 - <<'EOF'
import pathlib
p = pathlib.Path("datasets/riverbend-demo/responses.jsonl")
p.write_text(p.read_text().replace("850 dollars", "900 dollars"))
EOF

# 2. First run: integrity refusal, nothing scored, exit code 3.
PYTHONPATH=src python3 -m plumbline gate --config examples/riverbend.toml --out audits
echo $?   # 3

# 3. "Regenerate" legitimately — the hash change is the trace.
PYTHONPATH=src python3 -m plumbline seal datasets/riverbend-demo
#    dataset: 1c14ef2522da -> 44f59018fbe4

# 4. Second run: three independent checks catch the planted fact, exit code 1.
PYTHONPATH=src python3 -m plumbline gate --config examples/riverbend.toml --out audits
echo $?   # 1

# 5. Restore the demo bundle.
git checkout -- datasets/riverbend-demo
```

Three suites catch it on the second run, and two of them are above their
floors when they do:

| Suite | Score | Floor | Verdict | Why |
|---|---|---|---|---|
| `accuracy` | 0.8680 | 0.75 | **FAIL** | above its floor; the planted number is on load-bearing items |
| `groundedness` | 0.8166 | 0.70 | **FAIL** | above its floor; 900 appears in no source |
| `cross_language` | 0.6250 | 1.00 | **FAIL** | English now says 900, Spanish still says 850 |

That is the whole argument for the design. A pooled average absorbs one
fabricated fact — both `accuracy` and `groundedness` are comfortably over
their floors and fail on severity, not on score. And the same fact asked in
two languages cannot be quietly wrong in one of them.

The regression block in the same report closes the loop:

```
## Regression against baseline

**Numeric comparison refused.**

- the dataset hash differs: this run scored 44f59018fbe4, the baseline scored
  1c14ef2522da. The evidence changed, so the scores are not comparable numbers.

Overall verdict: **PASS → FAIL**.

Suites whose verdict changed:
- `accuracy`: PASS → FAIL
- `cross_language`: PASS → FAIL
- `groundedness`: PASS → FAIL
```

Re-sealing made the bundle runnable again. It could not make the run look like
the one before it.

## Comparing against a baseline

A baseline is a short committed record — provenance and one line per suite —
distilled from a report you were happy with:

```sh
PYTHONPATH=src python3 -m plumbline baseline \
  --from audits/<run-id>/report.json --out baselines/riverbend-demo.json
```

Point a target at it once (`[baseline] path = "..."` in the config, or
`--baseline` on the command line) and every later run reports what moved and
what flipped. Two things it will not do:

- It will not subtract scores across a **changed dataset hash or judge
  configuration hash**. Those runs used different evidence or a different
  instrument, and the difference would look like a measurement without being
  one. It says which hash moved and stops there — verdict flips are still
  named, because those stay meaningful.
- It will not let a delta smaller than a suite's **minimum detectable effect**
  pass as a finding. Such a move is reported as inside the noise floor, so
  nobody spends a week chasing a wobble the sample size could never resolve.

A refused comparison does not fail the build on its own; the audit is still
valid. Pass `--require-comparable-baseline` if you want it to.

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

## What is not implemented

Two things, both deliberate and both on the roadmap in `DESIGN.md`:

- **Live-target adapters.** Plumbline grades recorded transcripts. Something
  else has to produce `responses.jsonl` by talking to the system under test;
  the bundle format separates items from responses precisely so an adapter can
  slot in without changing anything that is scored.
- **Model-based judges.** The default judge is lexical, which is what makes
  the harness deterministic and keyless. A model judge would be optional,
  clearly separated, and flagged in every report that used one — a report that
  hid which judge produced it would not be a report worth defending.

Every suite in the specification's taxonomy is implemented, and every suite is
exercised by the bundled demo.

## Non-goals

Not a leaderboard. Not a general benchmark. Not a red-team service.
