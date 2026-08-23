# Definition of Done

Closes the gap the Quality & Metrics conformance row names against
itself: "no Definition of Done." `CONTRIBUTING.md` already states the
rule that governs *what kind* of change is acceptable here — a check
that cannot go red is a badge. This document is the narrower, mechanical
question: for a change that follows that rule, what has to be true
before it is finished, not merely working.

Every item below is either a command you can run or a question with a
factual answer. None of them is "looks good" — that standard cannot be
checked by the next person, which is the whole argument this repository
makes about checks in general, applied to itself.

## Every change

- [ ] `make verify` passes: lint (`ruff`), `mypy`, the full test suite
      under its coverage floor, and `site-check`. Not "passes except
      one flaky test" — see [`docs/operations-runbook.md`](operations-runbook.md)
      for the one test in this repository that is a known, environment-specific
      exception (root bypassing a read-only-directory permission check),
      and confirm any *other* failure is not being waved through as if it
      were that one.
- [ ] No new finding under a rule set this repository has recorded as an
      open gap (the wider ruff selection, `mypy --strict`, McCabe
      complexity) beyond what was already there. Widening a recorded gap
      silently is worse than not recording it, because a reader trusts
      the number in the README.
- [ ] A new check, suite, or gate ships with a test proving it can
      *fail* on a planted defect, not only a test proving it passes on
      good input — `CONTRIBUTING.md`'s own rule, restated here because it
      is the single most-skipped step in a change that otherwise looks
      complete.
- [ ] The commit message says what changed and, if it is not obvious,
      why — not only what file. A reviewer six months from now has the
      diff already; the message is for the reasoning the diff cannot
      carry.

## If `src/plumbline/` changed

Source changes move `harness_source_sha256`, which invalidates every
committed derived artifact. All of the following, not a subset:

- [ ] `audits/`, `baselines/`, `proof/matrix.{md,json}`, and
      `site/index.html` regenerated — in the order
      [`docs/operations-runbook.md`](operations-runbook.md#the-committed-audit-is-not-what-this-code-produces-or-baseline-or-matrix-or-sbom-or-site)
      describes, not by hand-editing any of them.
- [ ] `sbom.cdx.json` regenerated too, if `pyproject.toml`'s dependencies
      changed.
- [ ] Reproducibility checked, not assumed: a second, independent gate
      run against the same config produces a byte-identical report
      (`diff -rq` between the two output directories prints nothing).
- [ ] If a score, a floor, or a suite's behavior changed on purpose, the
      baseline was regenerated *because the change is real and you can
      say why* — never to turn a red reproduction step green without a
      behavioral reason. `CONTRIBUTING.md` names this as the failure mode
      this whole repository exists to argue against; it is worth
      checking against directly, not just trusting the regeneration
      commands to have been run for a good reason.

## If a claim this repository makes about itself changed

A "claim about itself" is anything a stranger could read and believe
without running code: a conformance-table row, a count (suites, tests,
files), a percentage (coverage, ruff/mypy findings), a stated version, a
documented exit code or CLI flag.

- [ ] The README's Standards Conformance table still describes reality —
      not only the row the change obviously touches. Adding a suite
      moves the suite count referenced in several rows, not just the AI
      Evaluation one; wiring in a new tool can flip a row from "not met"
      to "met" and should say so plainly rather than leaving stale
      "not met" language next to a passing check.
- [ ] Every count and percentage restated in the table is measured
      *today*, not carried over from the last time someone looked —
      `pyproject.toml`'s own dated comments (coverage %, wider-ruff
      finding counts) are the pattern to copy: state the number and the
      date it was true.
- [ ] `CHANGELOG.md`'s `[Unreleased]` section names the change, in the
      same voice as the entries already there — what closed, what it
      cost, what is still open — not a one-line summary that could apply
      to any PR.
- [ ] [`docs/metrics-ledger.md`](metrics-ledger.md) has a new row, if the
      change moved any metric it tracks. See that file for which ones
      and why appending there is a manual step nothing currently
      enforces.

## If a document's own claim about its gap changed

Several documents in this repository name a limitation against
themselves on purpose (the model card, the responsible-tech statement,
this file's own conformance row). If a change closes one of those named
gaps:

- [ ] The document says so, in place — not silently, and not by leaving
      the old "not met" language standing next to a change that met it.
- [ ] If the change does not fully close the gap, the document says
      exactly how much of it remains open, the same way this repository's
      "not met" rows already do. A gap half-closed and left undescribed
      reads as fully closed to anyone skimming.

## What this list is not

It is not a merge checklist enforced by CI — nothing here is a script,
and turning the mechanical items into one is a reasonable next step, not
a promise this document is making. It is not a substitute for review
either: a change can satisfy every line above and still be a bad idea,
which is a judgment call this list does not attempt to automate. What it
is: the difference between "the tests pass" and "this is finished,"
written down so that difference does not have to be re-derived by every
person who opens a pull request here.
