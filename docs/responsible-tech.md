# Responsible-tech statement

Dated 2026-08-22, alongside `v0.2.0`. Closes the gap the Responsible-Tech
Framework conformance row names against itself: "no dated ethics,
transparency, or residual-risk artifact." Revisit this alongside a future
MINOR or MAJOR version, or sooner if anything below turns out to be wrong in
practice — a residual-risk statement nobody revisits is a badge, and this
project's whole argument is that a badge is worse than an honest gap.

## Who this is actually about

Every other document in this repository is written from the point of view
of the harness and the person running it. This one is written from the
point of view of the people who are not in the room: residents applying for
benefits, checking a deadline, or asking a government chat system a
question they need answered correctly. Plumbline never talks to them. It
grades a system that might. Everything below is about the distance between
"Plumbline said PASS" and "this system served that person well."

## What Plumbline is not, said plainly

- **Not a certification.** A `PASS` means the suites a target's operator
  chose to enable, at the floors that operator chose, did not detect a
  problem on the evidence given to them. It is not a claim that the system
  is safe, fair, accurate, or fit for its purpose, and this repository does
  not use those words about a `PASS` anywhere else either — see the
  suite-by-suite "what this proves" notes in `report.json` for how narrow
  each one actually is.
- **Not a substitute for the people who should already be involved.**
  `representational_harms.py`'s own note says the shipped list "should be
  written with the communities the system serves." A harness that replaced
  that conversation instead of informing it would be a worse outcome than
  no harness.
- **Not a benchmark, and not evidence about any real system**, per the
  first line of the README, restated here because it is the single most
  important sentence in this repository and the easiest one to lose in a
  slide deck: `datasets/riverbend-demo` is invented, and no score produced
  from it means anything beyond "the instrument functions."

## Residual risks — present even when every suite works exactly as designed

**A green run is a floor someone chose, not a ceiling on harm.** Floors are
per-target configuration, set by whoever configures the target — a real
deployment could set every floor at the level its current, mediocre
performance already clears, and `plumbline gate` would report PASS
honestly, because that is what the config asked it to check. Nothing in
this harness second-guesses a floor a human committed to a reviewable file.
The review is the safeguard; a harness cannot supply the judgment a floor
represents.

**A suite that was never enabled catches nothing, and a `PASS` does not say
which suites ran.** It says so in every report — the suite table is right
there — but a `PASS` repeated in a status update, a slide, or a press
release routinely sheds the table it came from. A target that never enables
`privacy` or `adversarial` can pass every suite it did enable while leaking
personal data or complying with every injection attempt, and nothing about
the word "PASS" on its own discloses that. Read a verdict together with the
suite list it came from, every time, not as a single word.

**Lexical screens catch what is on their list, not what is wrong.**
`privacy.py` and `conduct.py` both say this about themselves — "pattern
matching finds identifiers, not judgment calls" — and it is worth saying
again here because it is an ethical limit, not only a technical one. A
system that discloses a caseworker's personal opinion about an applicant in
flowing prose, with no digits and no `@` in sight, passes the privacy screen
cleanly. The screen is real and worth having; it is not a promise that
nothing else is wrong.

**The demonstration dataset's coverage is not the world's coverage.**
`riverbend-demo` is English and Spanish, two registers, one fictional
mid-sized county's programs. A real deployment serves people in more
languages, at more literacy levels, with more disabilities, in more kinds
of hardship than two invented registers of two invented languages can
represent. `docs/first-real-target.md` says a real dataset has to come from
a real target's own transcripts, written by people who know the population
being served; this statement says why that is not a nice-to-have — a
harness whose test data does not reflect who is actually asking questions
will not catch what those people would have hit.

## Misuse this repository can name but not prevent

- **A floor set to guarantee a pass rather than to hold a bar.** The
  configuration is a reviewable file, which makes this visible in a diff —
  it does not make it impossible. A reviewer who does not ask "why this
  number" is the actual control here, not the harness.
- **Selective suite enablement as a quiet way to avoid a hard question.**
  Enabling `smoke` and `accuracy` while leaving `adversarial` and `privacy`
  off is a valid configuration and a legitimate way to phase in coverage —
  and an easy way to produce a clean-looking report about a system nobody
  checked for the things those two suites exist to check. The same
  suite-list discipline above is the only defense named in this document.
  *(Added 2026-08-27: it is no longer the only one. Every report and every
  terminal run now carries a `scope` block naming the implemented suites
  the run did not score and why, so the omission travels with the verdict
  instead of waiting to be noticed. It still does not prevent the misuse,
  and deliberately does not — see
  [ADR 0004](adr/0004-unscored-suites-are-disclosed-not-enforced.md).)*
- **Citing a `PASS` outside the context that produced it.** A verdict
  detached from its dataset hash, its floors, and its suite list is a
  claim this repository does not make and cannot back once it is
  detached — the seal and the provenance block exist precisely so a reader
  can always reattach them, but only if the reader goes looking.

## What this project does about it, and what it does not

**Does:** publishes the fail-open defects found in its own history, before
and after the fix, rather than only the fixed state (`CHANGELOG.md`,
`README.md`'s "What it caught in its own harness"); states the seal's limit
in the tool's own output, every time (`plumbline verify`); reports
UNVERIFIABLE rather than a pass whenever the evidence cannot support a
check; refuses to run a suite with nothing to score rather than reporting a
vacuous pass; documents what a screen does not prove inside the suite that
runs it, not only in a separate document a reader has to find.

**Does not:** decide what a real deployment's floors should be — that is a
policy decision for the people accountable to the population being served,
named as such in the README's Non-goals ("not a leaderboard, not a general
benchmark, not a red-team service"); audit anything continuously or in
production — a `plumbline record` capture is a snapshot, and a system can
change the day after one is taken; take accountability for a launch
decision made by reading its report. The report is evidence for that
decision. It is not the decision.

## This statement's own gap

This document was written inside the project it describes, by the same
process that builds the harness, and has not been reviewed by anyone
outside this repository — no affected community, no independent ethicist,
no one who has actually depended on a government chat system this tool
might one day grade. That is the same limit the README already states
about the harness's development process (see Status), applied to this
document instead of the code. Treat it as a starting statement to argue
with, not a finished one.
