# What it caught in its own harness

*A longer-form draft for external publication — a blog post, dev.to, or
similar — distinct from the terse version in the README's "What it caught
in its own harness" section. Same facts, written for a reader who has never
seen the repository, with room to walk through the mechanism rather than
just cite the result. Edit freely before publishing; this is a draft, not
a final copy.*

---

Plumbline is an evaluation harness: a tool that grades a government-facing
chat system against a set of automated checks and produces a report a third
party could defend. Thirteen of its fifteen suites were specified for it;
the other two it grew on its own, each from a real gap the first thirteen
turned out to have. Every one of them is supposed to catch a specific kind
of failure — a wrong number, a system that answers when it should refuse,
an answer built on the wrong source paragraph.

None of that is the interesting part of this post. The interesting part is
that at least five times, the harness itself got the grading wrong — and
every one of those times is published, with the broken behavior reproduced
first and the fix afterward, in the project's own changelog. Not because
publishing your own bugs is a nice thing to do. Because an evaluation tool
whose failure modes you can't read is not one you can actually trust, and
the only way to make that trust checkable is to show your work when the
work was wrong.

## The bug that scored silence as a perfect answer

Here is the shape of the first one, because it recurred three times before
it actually died.

A chat system that returns nothing — an empty string, a timeout, a crashed
backend — has obviously failed. But "failed" isn't automatically what a
grading suite records. Several of Plumbline's suites work by *screening for
the absence of something bad*: does the response leak personal data? Does
it contain a phrase from a list of things it should never say? Those checks
share a structure — they look for a match, and if they don't find one, the
item passes.

An empty response never contains anything. So it never matches. So it
passes. Not sort of passes — a real run, against the project's own
demonstration dataset (174 items at the time; it's grown since), had a
target answer nothing at all and scored a perfect `1.0000` on five
separate suites: groundedness, privacy, representational harms, fairness,
and cross-language consistency. The gate that's supposed to block a bad
system on merge returned `PASS`, exit code `0`.

The first fix tested `response.strip()` — if there's nothing left after
stripping whitespace, that's silence, and silence doesn't get to pass a
check phrased as an absence. That closed the empty-string case. It did not
close the case where a system answers with a single period. Or an emoji. Or
a zero-width space — a character that is, by definition, invisible and
takes up no width, and which `.strip()` does not touch, because it isn't
whitespace by that function's definition. All three of those are non-empty
strings. All three of them are exactly as devoid of content as an empty
one, and all three of them sailed through the same five suites at the same
perfect score, because "not empty" and "contains something a check can
read" turned out to be different properties, and the harness had only ever
tested for the first one.

The actual fix wasn't a longer blocklist of unicode edge cases. It was a
change of question. Instead of asking "is this response non-empty," every
suite now asks "does anything in this response survive normalization" —
the same content-token extraction the harness already used to score
answers, repurposed as a readability gate. A period survives `.strip()`
and dies at normalization. So does an emoji. So does a bare citation marker
with nothing around it. That one predicate is now something every suite in
the harness reads, silence included.

And there was a third round even after that, quieter than the first two.
Excluding an unreadable item from a suite's score — instead of counting it
as a failure — is the *correct* behavior when a check genuinely has nothing
to work with. But it opens a subtler version of the same hole: a target
that answers a third of a test corpus correctly and goes silent for the
rest can still pass every suite that *excludes* the silent items, because
none of those suites are the ones asking whether the target behaved
correctly in the first place — they're asking whether something bad is
*present*, and absence of evidence isn't presence of a problem to them. The
fix there wasn't inside any individual suite. It was a rule about the
*run as a whole*: if nothing enabled in a given configuration would ever
score silence against the target, the run refuses to produce a verdict at
all, rather than quietly reporting one that never had a chance to see the
failure.

Three rounds, one underlying mistake, each round closing a gap the
previous round's fix hadn't anticipated. That's not a flattering story.
It's the actual shape of finding out your absence-checks don't check for
absence.

## The bug a user found, not the harness

The next one didn't come from the harness's own defect-hunting. It came
from a team using Plumbline to grade a real assistant, who found an answer
their own human reviewer flagged and the automated report had scored
clean.

The question was about eligibility for a benefit. The answer was accurate,
well-cited, grounded in a real source document — and composed from the
*fare schedule* section of that document, which happened to share enough
vocabulary with the question to look, to a lexical scorer, like a
supported answer. The team's own summary of the bug was the sharpest
sentence in their report: *the audit passes that item, because no suite it
runs can say "wrong paragraph."*

They were right, and it's worth walking through why none of the existing
suites *could* say that, because it's a genuinely different kind of gap
from the silence bug. The silence bug was a mistake — an absence check that
didn't actually check for absence. This one wasn't a mistake in any single
suite. Every suite involved was doing exactly its job:

- The groundedness suite asks whether an answer is supported by *some*
  source the item had available. The fare paragraph was one of them. It
  is a real passage, and the answer genuinely came from it, so support was
  high.
- Citation validity asks whether a cited source id actually exists in the
  corpus. It did.
- Citation accuracy asks whether the cited passage supports the answer it's
  attached to. It does — completely, because that's the passage the answer
  was written from.
- Plain accuracy scores word overlap against a reference answer, pooled
  across the whole test set. One wrong-source item sinks into a mean and
  disappears.

Every question those suites ask, this item answers correctly. The question
nobody was asking was a different one: of the passages available, is this
the one that actually answers *this* question? That's a comparison between
candidate sources, not a check against a fixed reference, and it needed a
new suite built specifically to ask it — plus something none of the other
suites needed: a declared, reviewed answer to "which passage is supposed
to answer this," because a lexical scorer can compare two passages to an
answer, but it can't read the question well enough to know which one
*should* have been used. Items that don't declare that get reported
unverifiable, not passed by default — an unreviewed guess is worse than an
honest gap.

## The one where three red rows were one bug wearing three hats

The last one isn't a bug so much as a trap the previous fixes created.

Once you have several suites that all screen a response against the same
list of forbidden content, a single genuine incident — a system that leaks
a fragment of its own system prompt under a jailbreak attempt, say — trips
every suite that reads that list. Three red rows in a report. A reader
scanning for problem count sees three problems. There is one.

The fix wasn't to merge the suites, which would have thrown away the real
information that they're measuring different things and can fail
independently on different inputs. It was to compute, from that specific
run's own evidence, whether the suites that failed did so *on the same
item*, and print that finding directly into the report: these three
failed on the same one item, through the same shared input — read that as
one finding wearing three hats, not three findings. When the same suites
fail on genuinely different items in the same run, the report says that
too, because at that point they really are separate incidents that happen
to share a mechanism.

## Why publish this

None of these are flattering. Read individually they're a decent case for
not trusting this tool. Read together, I think they're the opposite case,
and it's the same argument the project keeps making about the systems it's
built to grade: a check that has never been observed failing is
indistinguishable from a check that cannot fail, and "cannot fail" is not
a property you want in something whose entire job is telling you when
something is wrong.

So the fail-open defects stay in the changelog, reproduced before they
were fixed, not summarized as "hardening" after the fact. There's a
defect-injection matrix that plants a specific problem for every suite the
harness ships and checks, on every test run, that the suite actually
catches it — twenty-one cases now, covering all fifteen suites, rebuilt
from scratch every time the code changes so it can't quietly go stale.
None of that proves the harness is right. It's evidence of the kind the
harness asks every system it grades to produce about itself, applied to
itself, which is the only really solid answer to "why should I believe an
evaluation tool's self-description" that we've found so far.

The tool is at [github.com/ChelseaKR/plumbline](https://github.com/ChelseaKR/plumbline).
The bundled dataset is entirely synthetic — a fictional county, invented
programs, made-up numbers — because it exists to demonstrate the
instrument, not to claim anything about a real system. It hasn't been
pointed at a real government-facing system yet; that's the honest next
step, not a finished one.
