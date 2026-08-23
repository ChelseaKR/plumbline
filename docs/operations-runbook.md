# Operations runbook

Closes the gap the Observability conformance row names against itself:
"no operations runbook." Written for two different people, because
Plumbline has two different operational surfaces and they fail in
different ways:

- **Someone gating a repository with it** ([Part 1](#part-1-running-the-gate-in-a-consuming-repository)) —
  the gate exited non-zero, or didn't exit, in a build.
- **Someone maintaining this repository** ([Part 2](#part-2-maintaining-this-repository)) —
  CI on `main` is red, a scheduled workflow needs attention, or a
  human-only duty (a key rotation, a retention sweep, a tag push) is due.

Plumbline is Tier C in the README's own terms: a command-line harness that
writes reports to a directory, not a service. There is no dashboard, no
SLO, no on-call. The observable surface is **the exit-code contract and
the reports it writes**, both already tested — this runbook is what a
person does with what those surfaces tell them, which is the part tests
cannot cover because the reader is a person, not an assertion.

---

## Part 1: running the gate in a consuming repository

Every row is keyed to the exit code table in the README — read that first
if a code here is unfamiliar.

### Exit 0 — nothing to do here

The build passed. If a score you expected to move did not, check
`--summary-file` output or the report JSON directly; a passing gate does
not mean nothing changed, only that nothing crossed a floor.

### Exit 1 — a suite failed

**What it means:** a real measurement, and it came back below floor.
**What to do:** read the named suite(s) and their `hard_failures` /
`item_records` in the report — not just the pooled score. A single
load-bearing failure can fail a suite whose pooled average still looks
fine; that is deliberate (see `groundedness.py`'s severity rule for the
canonical example). If the regression is expected — a deliberate model or
prompt change — regenerate the baseline (`plumbline baseline --from
<report> --out <path>`) rather than lowering the floor; a floor is a
policy choice made once, not a knob turned to make red green.

### Exit 2 — usage error

A command-line mistake, not a measurement. Fix the invocation; nothing
was scored, so there is nothing to interpret from the report (there is no
report).

### Exit 3 — integrity refusal

**What it means:** the evidence bundle's checksums do not match its
files, or a written report was edited after the fact, or a report claims
a run id its own contents do not generate. **This is not the same failure
as exit 1** — do not treat it as "the target got worse." It means the
thing being measured cannot be trusted to be what it claims, which is a
question about the recording pipeline, not the target.

**What to do:** read the specific refusal message — it names which file
and which hash disagreed (`plumbline verify` and the bundle-integrity
check both say precisely this, by design; see `audit.py`'s and `bundle.py`'s
docstrings for why the message is written to make the next step obvious
rather than generic). Re-record or re-seal the evidence from a known-good
source; never silently re-seal a bundle you cannot explain the edit to.
If this fires in CI on a bundle nobody touched, suspect the recording
job itself before suspecting Plumbline — a partial write, a truncated
checkout, or a line-ending conversion on `responses.jsonl` all produce
this same refusal.

### Exit 4 — configuration or environment error

**What it means:** the gate did not run at all. Common causes: an
unresolvable dataset path, a target config with an unknown suite name or
key, or — the one that surprises people — **a model judge configured to
make live calls inside `gate`**. `gate` refuses that outright by design
(see `judges.py` / `model_judge.py`): live network calls inside a
merge-blocking step are non-reproducible and the harness will not silently
tolerate that shape of nondeterminism. **What to do:** if the judge needs
live calls, precompute its cache in a separate, non-gating step and commit
the cache, then let `gate` run against the cache only. Otherwise fix the
named configuration key; the error names it specifically.

### Exit 5 — internal error

**What it means:** the harness itself crashed, or produced a result it
could not honestly aggregate. **This is a Plumbline bug report, not a
target finding.** Nothing was measured — do not merge past this code the
way exit 1 sometimes gets waved through as "known flaky." **What to do:**
capture the traceback (printed to stderr) and the exact command, and file
it against this repository. If it reproduces on the bundled demo
(`examples/riverbend.toml`), that is the fastest way to confirm it is not
local to your dataset before reporting it.

### The gate hangs instead of exiting

Not one of the six documented codes, so treat it as its own symptom.
Known causes, in the order to check them:

1. **A model judge is unreachable and its retry/backoff policy is long.**
   The judge config's `timeout_seconds` and `retries` bound this; a
   misconfigured judge (or a CI runner with blocked egress reaching an
   endpoint it should never need to reach — see exit 4 above, this is the
   case that slips past that refusal because the calls are *permitted*
   but the network is down) can still make a job time out rather than
   fail cleanly. Set a job-level timeout in CI regardless of the judge's
   own settings; a merge-blocking step should never depend solely on a
   third party's timeout being honest.
2. **`gate/plumbline-gate.sh`'s pin resolution is retrying against
   unreachable git remotes.** Check `PLUMBLINE_CACHE_DIR` for a stale
   half-written checkout and clear it; see `gate/README.md`'s environment
   variable table.
3. **A subprocess adapter's child process is not exiting.**
   `adapters/subprocess_cli.py` enforces its own timeout and output
   ceiling by killing the child, so a genuine hang here that outlives
   `timeout_seconds` in the adapter config is itself a bug — report it
   the way you would exit 5.

### `plumbline baseline` comparisons keep refusing as "not comparable"

Expected, not a fault, whenever the dataset hash or the judge
configuration hash legitimately changed — the comparison is refused
rather than computed on a bar that no longer describes the same
instrument. Regenerate the baseline from a fresh run once the change is
intentional; see `baseline.py`'s own docstring for the two hashes it
checks and why.

### `plumbline verify --key-file` fails to verify a signature

A shared-secret (HMAC-SHA256) signature failing to verify means either
the wrong key file, or the report bytes changed after signing —
`verify_report` (integrity) already runs first, so this is specifically
about *who* attests to the report, not whether it was edited. Treat a
failed verification the same way as exit 3: an integrity question about
provenance, not a score to chase down.

---

## Part 2: maintaining this repository

### CI on `main` is red

Two jobs, two different kinds of red — see `.github/workflows/tests.yml`'s
own comments for why they are split:

- **The `tests` matrix (Python 3.11–3.14) is red on one version only.**
  Usually a standard-library deprecation warning that a newer
  interpreter has escalated, not a real regression. Reproduce locally
  with that interpreter version before assuming the code is wrong.
- **The `tests` matrix is red on every version, or the `quality` job is
  red.** Treat as real. The `quality` job runs `make verify` — lint,
  `mypy`, the test suite with its coverage floor, and `site-check` — so
  read which sub-step actually failed before guessing.

### "the committed audit is not what this code produces" (or baseline, or
matrix, or SBOM, or site)

**The single most common way this repository's own CI goes red**, and
the one this runbook exists partly to save the next person from
re-deriving from scratch: any edit under `src/plumbline/` moves
`harness_source_sha256`, which is folded into every committed report's
provenance. The fix is not "revert the edit" — it is regenerating the
derived artifacts, **in this order**, because the baseline is
self-referential (it is built from a report, and its own hash then feeds
back into the run id of the *next* report that names it):

```sh
# 1. Run the gate once, against whatever baseline is currently committed.
#    This report's run id will usually be unchanged (the run id does not
#    depend on harness_source_sha256 directly) — but its provenance now
#    carries the new source hash.
PYTHONPATH=src python3 -m plumbline gate --config examples/riverbend.toml --out audits

# 2. Rebuild the baseline FROM that report. Its harness_source_sha256 now
#    matches the current tree, which is what tests/test_self_application.py
#    checks. Its own content — including source_run_id — has changed, so
#    its hash (baseline_sha256) has changed too.
PYTHONPATH=src python3 -m plumbline baseline --from audits/<run-id>/report.json --out baselines/riverbend-demo.json

# 3. Run the gate again. Because the baseline's content changed, the run id
#    changes too (baseline_sha256 is one of the run id's inputs) — this is
#    the ONE new run id you commit; delete the run 1 output.
rm -rf audits/<run-id-from-step-1>
PYTHONPATH=src python3 -m plumbline gate --config examples/riverbend.toml --out audits

# 4. Everything downstream, from this final run:
PYTHONPATH=src python3 tools/defect_matrix.py
PYTHONPATH=src python3 tools/build_sbom.py     # only if pyproject.toml's deps changed
PYTHONPATH=src python3 tools/build_site.py

# 5. Prove reproducibility before committing: a second, independent run
#    must produce byte-identical output.
PYTHONPATH=src python3 -m plumbline gate --config examples/riverbend.toml --out /tmp/verify
diff -rq audits/<final-run-id> /tmp/verify/<final-run-id>   # must print nothing
```

Skipping step 2–3's second gate run is the mistake to watch for: it
leaves a committed report that compares against a baseline the report
itself doesn't match, which `tools/build_site.py`'s own drill catches
(`REFUSED: the documented command produced [...], but the committed
report is [...]`) — a loud, correct failure, but a confusing one to hit
cold. If `pyproject.toml`'s dependencies changed, also run
`tools/build_sbom.py` before the final `build_site.py`.

### A security workflow found something

- **Semgrep (`security.yml`) or gitleaks (pre-commit)** flags a pattern:
  triage like any SAST finding — most are either a true positive to fix
  or a documented, narrow suppression at the flagged line, never a
  blanket rule disable.
- **Full-history TruffleHog** flags a verified secret: rotate it
  immediately outside this repository (the credential, not just the
  commit), then decide separately whether history needs rewriting — that
  is a judgment call with its own blast radius, not a reflexive
  `git filter-repo`.
- **Dependabot** opens a PR bumping a pinned action SHA: review the
  diff at the pinned commit before merging, the same as any other action
  update; a compromised action would look identical to a routine bump in
  the PR title alone.

### The PyPI publish workflow needs to run

`publish-pypi.yml` is manual-only (`workflow_dispatch`, typed
confirmation) by design — see the workflow's own header. Before it can
succeed even once: PyPI's Trusted Publisher must be registered for
`plumbline-eval` against this repository and workflow file. That
registration is a PyPI account action nobody in this repository's own CI
can perform; it is a standing, human-only prerequisite, not a one-time
setup step to forget about.

### `pages.yml` fails to deploy

Reproduce locally before touching CI: `make site-check` runs both
`tools/build_site.py --check` and `tools/check_site_a11y.py`, the same
two checks the workflow runs before `actions/deploy-pages`. A failure
here is never a Pages platform problem; it is one of those two checks
correctly refusing to publish a page that does not match either the
committed evidence or this repository's own accessibility standard.

### The coverage floor was breached

`make test` already fails the build; `coverage report -m` (or the
`show_missing` output `make test` prints) names the uncovered lines
directly. Add the missing test rather than lowering `fail_under` in
`pyproject.toml` — that floor is set below a real measurement on purpose,
the same reasoning as every suite's own floor.

### A `mypy` or `ruff` upgrade surfaces new findings on unchanged code

Both floors are pinned (`ruff>=0.15.0`, `mypy>=1.13.0`) but not pinned to
an exact version, so a tool release can add a check that a previously
clean codebase now fails without a line of this repository having
changed. Treat it as a real finding to fix, the same as if a person had
written the offending line yesterday — a tool getting stricter is not a
reason to suppress what it now sees.

### A release needs to be tagged, or the tag push is blocked

Tagging `vX.Y.Z` and pushing it is what triggers `release.yml` (SBOM
check, OpenSSF Scorecard, keyless Sigstore signing, a published GitHub
Release). This is a human-only action in this repository's current setup
— an agent session's own git credentials cannot push a tag or create a
release here — so if a version bump has merged and no tag follows, the
release step is waiting on a person, not a workflow.

### The recordings retention/redaction sweep

`plumbline retire --max-age-days N` (see `retention.py`) screens a
recorded bundle for content past its retention window and can redact or
remove it. **Nothing in this repository schedules that command.** It is
a manual or externally-cron'd duty for whoever holds recorded evidence
with a stated retention period — the harness enforces the *screening
logic* once asked, not the *asking*. Anyone committing to a retention
period in `docs/recordings-data-card.md` needs their own scheduled job
(cron, a CI schedule trigger, a calendar reminder) to actually invoke it;
this is named here because a retention policy nobody runs is
indistinguishable from no retention policy at all.

### Rotating the HMAC-SHA256 report-signing key

`signing.py`'s signature is a shared secret, not a PKI keypair — see its
own docstring for why (it attests to whoever else holds the same key
file, not to the public). If a key file leaks or a signer's access
should be revoked: generate a new key, distribute it out of band to
every legitimate verifier, and re-sign only the reports that still need
a valid signature going forward. Old signatures made with the retired
key do not become false — they remain evidence that *that* key signed
*that* report at the time; revoking trust in the key is a decision made
by whoever relies on it, not an operation this repository's tooling
performs for you.

---

## What this runbook is not

It does not cover the target under evaluation — a target failing a suite
is Part 1's exit 1, and what to do about the target itself is the
target operator's call, informed by the suite's own report, not this
document's. It also does not promise completeness: it is what has
actually been hit once (the baseline regeneration order above, notably)
or is a clear enough inference from the code to write down before it is
hit. Add to it the next time something breaks in a way this file did not
anticipate — a runbook that stops updating is the same badge this whole
project argues against.
