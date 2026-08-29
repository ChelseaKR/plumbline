# Improvement plan, 2026-08-28

An audit of the two open issues and of the gates themselves, on the principle
this repository already argues for: **a check that cannot fail is worse than no
check.** Everything below was executed except where marked, and every guard
added or repaired was run against a deliberately introduced fault before any
green result was trusted.

## What the audit found

Plumbline works, and it is the more careful of the two repositories audited
today. `make verify` exited 0 on a clean checkout before any change. The
bundled demo audits end to end, `plumbline validate` and `plumbline verify`
behave as documented, and the README's central claims were checked by running
them rather than by reading them.

Several of the traps this audit looks for are already closed here, deliberately
and with the reasoning written down:

- The tamper drill captures exit codes explicitly instead of leaning on `&&`,
  "a drill that asserts only *did not exit 0* would be satisfied by the harness
  crashing."
- The reproduction check uses `git status --porcelain`, not `git diff` alone,
  because a moved run id writes a *new, untracked* directory and a diff would
  see nothing.
- `uv sync --locked`, never `--frozen`, with the reason in a comment.
- `plumbline validate` treats a file **present but not listed** in
  `checksums.json` as an integrity refusal. Verified by planting one: exit 3.
  The checksum check is not blind to an entry never written.
- The accessibility suite refuses a target that declares *no* contrast pairs
  rather than passing vacuously.
- TruffleHog's Lob detector is excluded by detector rather than by path,
  explicitly so the scan is not blinded to secrets in `tests/`.
- No shell `for` loop over checks, no `cmd && cmd2 || echo`, no exit code read
  through `tail`. The one `head -n 1` parses a report path; the exit code comes
  from `${PIPESTATUS[0]}`.
- The coverage floor (90) sits below the measurement (93) rather than above it.

Two gaps were found anyway, and both are of the shape the repository names best
when it is looking at a target rather than at itself.

## Issue classification

| Issue | Class | Disposition |
|-------|-------|-------------|
| #32 `control_labels` never sees `<button>` | **Already fixed, not closed.** Fixed by PR #38 (`b3acb14`), more thoroughly than the issue proposed | Verified by running the issue's own repro; commented, left open for the owner |
| #31 `action.yml` can surface a stale run's verdict | **Already fixed, not closed.** Fixed by the same PR | Verified by reading the replacement; commented, left open for the owner |

Neither issue was wrong when filed. PR #38 landed both fixes without a
`Closes #NN` line, so both stayed open. Verified rather than assumed:

- `<button>` is in `CONTROL_TAGS`, and the fix goes past the issue's suggestion:
  an icon-only button fails, a text button passes, an `aria-label` button
  passes, and a button whose only text sits inside `aria-hidden="true"` fails
  with that stated as the reason.
- `action.yml` no longer globs the output directory. It reads the report path
  from the line the run itself printed, takes the gate's status from
  `${PIPESTATUS[0]}` rather than from `tee`, uses `[[:space:]]` rather than the
  GNU-only `\s` so a BSD `sed` on a macOS runner does not silently produce an
  empty path, and **fails with exit 5** if the gate measured something and the
  step cannot read a verdict back — rather than reporting success with no
  verdict, which is the failure it was reported for.

## Phases

### Phase 1 — the page's contrast check could not see an unlisted colour — DONE

`tools/check_site_a11y.py` proved that nine hand-written `CONTRAST_PAIRS` meet
WCAG AA. It was silent about a colour added to `:root` later and never added to
that list.

This is the same shape the harness refuses one level down: a file present but
not listed in `checksums.json` is an integrity refusal, and a target declaring
no contrast pairs is a failure, not a vacuous pass. The page that holds targets
to that standard was not held to it — the objection its own docstring raises
about a standard that "only ever points outward."

`palette_coverage` is the eighth check. Every declared colour is in a checked
pair or in `UNCHECKED_PALETTE_VARS` with a written reason. It also refuses a
stale exemption and palettes whose halves declare different colours.

One colour is exempt today: `--rule`, a 1px border, whose bar is WCAG 1.4.11's
3:1 for non-text rather than the 4.5:1 this check measures. It was already
outside the list; what changed is that the omission is a decision on the record.

**Break:** adding `--warn:#ffcc00` to both palettes of the real `site/index.html`
leaves `contrast` reporting its nine pairs clean and makes `palette_coverage`
fail, exit 1. Restored; the page is byte-identical.

### Phase 2 — `make verify` was green on trees CI rejects — DONE

Three steps in `tests.yml` were inline script with no target: the byte-for-byte
reproduction, the report-seal re-check, and the tamper drill. The Makefile said
so on purpose, because both mutate the working tree. That reasoning was right
about the symptom and wrong about the cure — neither needs to mutate anything.

`make reproduce` writes into a temporary directory and compares with `diff -r`,
which fails on a changed byte, a report no longer written, *and* an uncommitted
directory a moved run id would create. `make tamper-drill` tampers with a copy.
Both are in `verify`; the checkout is untouched by either. Both carry a floor
against passing over nothing.

The matrix job keeps its property: its steps call targets that use plain
`python3`, because `make` is not a Python package and routing the suite through
a target must not spend the claim that Plumbline runs on the standard library
alone.

**Breaks:** an inline CI-only step, and dropping `reproduce` from `verify`, each
fail `tests/test_ci_parity.py`. Pointing the drill's edit at a string absent
from the file makes it fail with "expected exit 3 (integrity refusal), got 0" —
the drill detects a tamper that never landed.

### Phase 3 — documents that did not match behaviour — DONE

The README's CI/CD row now says the workflow and the Makefile are one gate and
names the exemption; the Accessibility row names the eighth check and why it
exists.

## Open, and deliberately not closed here

- **`security.yml` is outside the parity rule.** Its semgrep step runs in a
  pinned container and its secret scan is a pinned marketplace action; neither
  is a shell command a Makefile could run identically. `make sast` is added as a
  local approximation and says so. Closing this properly means either running
  semgrep through the CLI in CI or accepting that the two differ.
- **`pages.yml` runs its two site checks as inline script.** They are the same
  two `make site-check` runs, but that job uses a bare interpreter with no uv
  while `site-check` goes through `uv run`. Wiring them together means changing
  either the target or the deploy job, and this is the workflow that publishes
  the live page; it was left alone rather than changed in an audit pass.
- **TruffleHog runs `--only-verified`.** A secret whose service has no verifier,
  or that has already been rotated, is not reported. That is a deliberate
  false-positive trade and it is not written down anywhere as a limit of the
  scan. It is a documentation gap rather than a defect.
- **`.semgrepignore`'s comment described the opposite mechanism** — FIXED, but
  worth recording, because the coverage it produces was an accident. A
  repository-root `.semgrepignore` *replaces* semgrep's built-in ignore list
  rather than extending it, and the built-in list drops `tests/`. Measured both
  ways on 2026-08-28: with the file present, 77 of 77 tracked Python files are
  scanned; with it moved aside, 46 are, and all 31 files in `tests/` are among
  the 32 skipped. So this repository's tests are scanned only because someone
  added that file for an unrelated reason (one HTML fixture), and the comment
  said the defaults still applied. Corrected, with the measurement and a warning
  that a broad path added there silently takes the coverage back.
- **`mypy` checks `src/plumbline` only.** `tools/` holds two gate scripts and is
  linted by ruff but not type-checked. Documented in the Makefile as deliberate.
- **The three Dependabot PRs (#35–#37)** were left alone; merging is not this
  pass's to do.
