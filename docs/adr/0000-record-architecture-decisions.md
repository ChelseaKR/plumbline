# 0000. Record architecture decisions

- Status: Accepted
- Date: 2026-08-17

## Context

This repository already argues, at length and in public, that a claim without a
record behind it is not evidence. `DESIGN.md` carries the architecture and an
acceptance record; `proof/matrix.md` carries an observed failure for every
suite; `CHANGELOG.md` carries every fail-open defect, reproduced before it was
fixed.

What none of them carries is the reasoning behind the decisions that shaped the
harness: why integrity refusal gets its own exit code rather than folding into
failure, why silence is scored rather than skipped, why the default judge is
lexical, why the runtime has no third-party dependencies. Those decisions are
visible in the code and defended in the README, but the alternatives that were
weighed and rejected are not written down anywhere. A reader who disagrees with
one of them cannot tell whether it was considered and rejected or simply never
considered, and neither can a future maintainer.

## Decision

Architecture decisions are recorded here, in `docs/adr/`, one Markdown file per
decision, numbered sequentially from this one and never renumbered.

An ADR states the context, the decision, and the consequences including the
ones that are unwelcome. It names the alternatives that were rejected and why.
It is a record of what was decided and when, so it is not rewritten when the
decision changes: a later ADR supersedes an earlier one and says so, and the
superseded file stays where it is with its status updated.

A decision needs an ADR when reversing it would be expensive or when a reader
could reasonably expect the opposite choice. Routine changes do not.

This ADR is the seed. The decisions listed in the Context above predate it and
are documented in `DESIGN.md` and the README; they are not backfilled here
retroactively, because an ADR written after the fact about reasoning nobody
recorded at the time would be exactly the kind of confident, unverifiable
artifact this project refuses to produce elsewhere.

## Consequences

- New architectural decisions carry a reviewable record of their alternatives.
- The existing decisions stay documented where they already are. The ADR log
  starts from today rather than pretending to a history it does not have.
- One more file per significant decision, and the discipline to write it while
  the alternatives are still fresh rather than afterwards.

## References

- Michael Nygard, "Documenting Architecture Decisions" (2011), the origin of
  this format.
