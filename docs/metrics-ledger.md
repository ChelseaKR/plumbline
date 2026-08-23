# Metrics ledger

Closes the other half of the gap the Quality & Metrics conformance row
names against itself: "no metrics ledger." The README's own conformance
table states these numbers *as of the date printed next to them* —
correct at that moment, silently stale the next time any of them moves.
This file is the history those single point-in-time numbers do not
carry: what each metric was, when, and — where the change is worth a
sentence — why it moved.

**Append a row, never edit one.** A ledger that could be rewritten in
place would only ever show today's numbers looking inevitable; the
point is to show the actual trajectory, including the times a number
went the wrong way before it went the right one (mypy's error count
below, for one). This is the same argument `history.py`'s own docstring
makes for run-level score history, applied here to the repository's own
engineering metrics instead of a target's suite scores.

**Every row below is a real measurement against the tagged or merged
commit named**, not a number carried forward or recalled from memory —
each was produced by checking out that commit in an isolated worktree
and running the same commands `make verify` runs today. Two rows earlier
than that discipline started are marked as such rather than backfilled
with a guess.

**This ledger is hand-maintained. Nothing enforces that a row gets
added.** Unlike `audits/` or `proof/matrix.md`, no test fails if this
file falls behind reality — see [Definition of Done](definition-of-done.md)'s
checklist item for the closest thing to an enforcement mechanism this
repository has today, which is a person remembering to look. Recorded
here, plainly, rather than implied: a ledger nobody is reminded to
update decays the same way an unscheduled retention sweep does (see the
[operations runbook](operations-runbook.md#the-recordings-retentionredaction-sweep)),
and pretending otherwise would be exactly the kind of badge this project
argues against.

## What each column means

- **Suites** — suite classes actually registered (`grep -c '^@register'
  src/plumbline/suites/*.py`), not suite *files* — `grounding.py` alone
  registers three.
- **Tests** — `unittest discover -s tests` test count. One of these has
  always failed under the account this ledger was measured from: a test
  that forces a write failure via a read-only directory, which `root`
  bypasses — see the operations runbook. Not counted as a real failure
  in any row below.
- **Coverage** — branch coverage over `src/` only (`coverage run
  --branch --source=src`), matching `pyproject.toml`'s
  `[tool.coverage.run]` once that section existed; measured the same way
  by hand for the two rows before it did.
- **Ruff narrow** — `ruff check src tests tools` using whatever that
  commit's own `pyproject.toml` configured (the actual `make lint`
  command). 0 is not a given: v0.1.0 measures 12, all `F541`, before the
  documented ignore for that rule existed.
- **Ruff wide** — findings under the portfolio set
  `E,W,F,I,UP,B,SIM,RUF`, measured, not enforced, by explicit
  `--select` at every point (this set has never lived in
  `pyproject.toml`, so the number is comparable across rows the way the
  narrow column isn't). The `E501` (line-length) count is given
  alongside where it was recorded; not every row separated it out.
- **Complexity** — functions exceeding McCabe complexity 10, under
  `ruff check --select C90 --config lint.mccabe.max-complexity=10`.
  Measured, not enforced.
- **mypy** — default-mode error count, then the `--strict` count
  alongside once mypy was installed as a dependency at all (`uv run
  --with mypy==2.3.1 mypy ...` for the rows before it was, to hold the
  tool version constant across the comparison).

## History

| Date measured | Commit | Suites | Tests | Coverage | Ruff narrow | Ruff wide (E501) | Complexity | mypy default (`--strict`) | Note |
|---|---|---|---|---|---|---|---|---|---|
| 2026-08-22 (retroactive) | `v0.1.0` (`1dbd58d`) | 14 | 459 | 94% | 12 | 298 (n/a) | 14 | 19 (not measured) | First tagged release. `make lint` was not yet clean in the strict sense: all 12 narrow findings are `F541`, before `pyproject.toml` carried the documented ignore for it. |
| 2026-08-22 (retroactive) | pre-session (`80a1c90`) | 14 | 502 | 94% | 0 | 301 (232) | 14 | 27 (not measured) | State this whole feature-expansion effort started from; matches the numbers `pyproject.toml`'s and the README's own dated (2026-08-17) comments already carried, cross-checked here rather than assumed. |
| 2026-08-22 (retroactive) | `v0.2.0` (`93b1ca9`, #8–#14) | 15 | 566 | 94% | 0 | 315 (235) | 17 | 29 (not measured) | `conversational_integrity` suite added (multi-turn items); report signing, SARIF export, run history, retention/redaction, and supply-chain closure shipped in the same round. mypy's default-mode error count moved 27→29 as a side effect — nobody was fixing mypy findings yet, so an unrelated increase from new code is expected, not a regression. |
| 2026-08-22 | mypy wired (#20, `fa81497`) | 15 | 566 | 93% | 0 | 317 (237) | 17 | 0 (174) | mypy's default mode fixed and wired into `make lint`/CI: 29 errors → 0, mostly a `Judge` Protocol extended to its full contract (see `CHANGELOG.md`). Coverage, wide-ruff and complexity moved slightly as a side effect of the guard clauses and comments the fix itself added — recorded rather than smoothed over, per this ledger's own append-only rule. `--strict` measured for the first time here: 174, recorded as the next open gap rather than a target. |
| 2026-08-22 | site a11y check (#21, `b31122c`) | 15 | 593 | 93% | 0 | 317 (237) | 17 | 0 (174) | `tools/check_site_a11y.py` and its 27 tests added; no `src/plumbline` change, so every code-quality metric above is unchanged from the previous row — only the test count moved. |
| 2026-08-22 | operations runbook (#22, `3a6a4ff`) | 15 | 593 | 93% | 0 | 317 (237) | 17 | 0 (174) | Documentation only; no metric here moved. |

## What this ledger does not track

Suite *scores* against the bundled demo target — those belong to
`plumbline history` (`history.py`), which is a longitudinal record of
runs against one target's evidence, a different thing from this
repository's own engineering metrics. It also does not track anything
without a command behind it in this file's own "what each column means"
section above; a metric that cannot be reproduced by the next person is
not one this ledger is willing to assert a number for.
