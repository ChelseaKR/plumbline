# 0001. Longitudinal history reports an observation, not a statistic

- Status: Accepted
- Date: 2026-08-22

## Context

`baseline.py` compares one finished run against exactly one stored bar. It
refuses the comparison outright across a changed dataset or judge
configuration hash, and it qualifies every surviving delta against that
suite's minimum detectable effect (MDE) — the smallest true drop a
same-sized run could tell apart from noise. That machinery is deliberately
conservative, and every number it prints is backed by the same statistical
apparatus (`stats.py`) the suite scores themselves are.

It also means a slow drift is invisible to it by construction: a suite
creeping downward by less than one comparison's MDE on each individual run
never accumulates into anything, because each comparison is evaluated in
isolation against the same fixed point. `history.py` exists to give a reader
something to look at across many runs instead of one pair.

The question this ADR answers: once there is a sequence of runs to look at,
how far does this module go in characterizing the trend? A real answer —
"is this suite's score truly declining, and by how much, with what
confidence" — is a hypothesis-testing question, and this codebase already
has one apparatus for exactly that class of question (`stats.py`,
confidence intervals, MDE). Building a second one for sequences, with its
own assumptions about autocorrelation, variance and multiple comparisons
across suites, is a materially larger undertaking than anything else this
feature set adds, and a wrong one would be worse than none: a false
"declining" is a report a maintainer chases for nothing, and false comfort
from a trend statistic that quietly doesn't apply to this data is exactly
the kind of confident, unverifiable artifact this project refuses to ship
elsewhere.

## Decision

`history.trends()` reports one plain, structural fact: whether a suite's
score was non-increasing across every step of the trailing N comparable
runs, with at least one real decrease (not merely flat). It computes no
interval, no p-value, and no significance threshold of its own. The number
printed next to a "declining" finding is the same list of scores a reader
could get by opening N report.json files and reading one field out of each;
`history.py` only saves them the trouble and the risk of missing that it was
still going the same direction.

The finding is deliberately named a "trend" and described in its own output
as "an observation, not a hypothesis test" — the module's docstring and
`render_terminal`'s own wording both say so, so a reader cannot come away
believing this makes a stronger claim than it does. `history check` is
off by default in CI (`--fail-on-decline` is opt-in); the pairwise baseline
comparison remains the only one of the two whose refusal-to-compare and
MDE-qualified delta are load-bearing for a merge gate.

## Consequences

- A real, slow regression that never exceeds a single comparison's MDE now
  has a mechanism that can surface it, without touching the baseline
  comparison's own guarantees at all.
- The trend finding is easy to verify by eye and easy to reproduce by hand;
  it is also easy to fool with a small window (`--min-streak`) or to miss
  a decline that dips and partially recovers within the window. Both
  limits are named in `history.py` and in `render_terminal`'s own output
  rather than left for a reader to discover.
- If a future need genuinely requires a trend statistic — an actual
  hypothesis test over the sequence — it is a new decision and probably a
  new ADR, not a quiet upgrade of this module's "declined every run" line
  into something that sounds more rigorous than it is.

## Alternatives considered

- **A trend statistic (e.g., Mann-Kendall, or a regression slope with its
  own confidence interval).** Rejected for now: real, but it is a second
  hypothesis-testing apparatus next to `stats.py`, with its own assumptions
  this dataset has not been checked against, for a beyond-spec feature. It
  is the natural next step if the plain observation here turns out not to
  be enough in practice.
- **Directory-scan ordering instead of an append-only file.** Rejected:
  reports carry no timestamps by design, and a directory's modification
  times are not evidence — they move on a checkout, a rebase, or a `touch`.
  An append-only file makes the order an explicit, committed fact instead
  of an inferred one.

## References

- `src/plumbline/history.py`, module docstring.
- `src/plumbline/stats.py`, the existing MDE/CI apparatus this module
  deliberately does not duplicate.
- `docs/feature-expansion-ideas.md`, idea 6, which named this exact risk
  before the module was written: "this is the one idea here that risks
  adding an assertion the harness cannot yet back with the same rigor as
  its other numbers."
