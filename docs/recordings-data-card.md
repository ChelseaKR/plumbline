# Data card: recordings

A short description of what `plumbline record` writes to disk, and what
governs how long it stays there — the two things the README's Data
Governance conformance row names as missing.

## What a recording is

`plumbline record` asks a live target every question in a question set and
writes the answers as a new, sealed evidence bundle. It is the only command
in this harness that opens a socket. Everything else — `audit`, `gate`,
`validate` — grades a bundle that is already on disk and never talks to the
target itself.

A recorded bundle's `manifest.json` carries a `recording` block naming when
it was made (`recorded_at`), which adapter reached the target, and which
question set it answered. The response text itself is the target's own
output, verbatim: this harness does not summarize, truncate, or filter it
before writing it to `responses.jsonl`.

## What it can contain

The bundled demonstration dataset is synthetic — a fictional county,
fictional programs, fictional numbers — and recordings made against it carry
nothing real. A recording made against an actual government-facing chat
system is different: **the target's answers can contain whatever personal
data the target itself discloses**, echoes back, or is asked to withhold and
fails to. That is exactly the failure mode `privacy.py` exists to score, and
a recording is the raw material that check runs over.

`.gitignore` keeps recordings out of this repository by default. That is a
default, not a policy — nothing about it says how long a recording should
sit on whichever disk actually holds it, or what has to happen before it is
deleted.

## What governs how long one stays

`plumbline retire <bundle> --max-age-days N [--redact]`:

- Screens every recorded response for the same personal-data patterns
  `privacy.py` scores with (`judges.LexicalJudge.pii_in`) — Social Security
  numbers, phone numbers, email addresses, payment card numbers by shape.
- Within the retention window: reports what it found. Never fatal — the
  window has not closed yet.
- Past the window, with a flagged pattern still present and `--redact` not
  given: **refuses**, the same posture the gate takes on a failing suite.
  Silence about a retention policy is not a retention policy.
- With `--redact`: rewrites every flagged span in place as
  `[REDACTED:<kind>]` and reseals the bundle — the only legitimate way to
  change evidence, and it always leaves a trace, because the bundle hash
  changes.

## What this does not claim

Screening here is the same pattern match `privacy.py` scores with, and it
has the same limit: **pattern matching finds identifiers, not judgment
calls**. A clean screen — before or after redaction — means no shipped
pattern matched, not that no personal data remains. A response that
describes a neighbour's case in prose, or a name and an address spelled out
with no digits or `@` in sight, is exactly the kind of disclosure this check
was never built to catch. Treat a passing `retire` run as "the specific
things this harness knows how to look for are gone," not as "this recording
is safe to keep or share."

This is not a stated legal retention obligation for any jurisdiction. It is
a mechanism a deployer can point a real policy at — set `--max-age-days` to
whatever that policy requires — not a substitute for having one.
