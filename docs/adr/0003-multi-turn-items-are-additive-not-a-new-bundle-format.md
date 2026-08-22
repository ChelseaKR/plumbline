# 0003. Multi-turn items are additive fields, not a new bundle format

- Status: Accepted
- Date: 2026-08-22

## Context

Every suite before this change read `bundle.response_for(item.id)` — one
recorded response for one item — and nothing about a conversation's shape
before that final answer. A target that leaks a forbidden phrase, or drops
a refusal, midway through a conversation and then produces a clean final
answer was invisible to every suite, the same way a wrong-paragraph answer
was invisible to every suite before `passage_attribution` existed (see the
README, "Wrong paragraph, right document").

Closing that gap needs the bundle format to represent a conversation with
more than one exchange. Two shapes were available: extend `Item` and its
recorded response with optional multi-turn fields, or introduce a second,
parallel item/response shape (`format_version = 2`, or a `conversation`
item type distinct from the existing single-turn one) that the existing
174-item demo bundle, every fixture, and every consuming repository's own
bundles would need to either migrate to or be read alongside.

`bundle.py`'s own `FORMAT_VERSION` constant and the loader's refusal of an
unsupported version exist because a format change is exactly the kind of
decision this ADR log is for: reversing it, or reader expectations about
it, would be expensive.

## Decision

Additive fields, not a new format:

- `Item.turns: list[str]`, defaulting to empty — follow-up user turns after
  `prompt`, which stays turn one. `[]` is byte-identical to every item this
  harness has ever loaded.
- A response record's `turn_responses`, an optional key alongside the
  existing `response` field. Its own field, not a replacement: `response`
  stays exactly what every suite that has never heard of multi-turn items
  already reads, and `turn_responses` is additional evidence only
  `conversational_integrity.py` reads.
- No cross-check that `turn_responses[-1] == response`. The two started
  cross-checked and a real test broke on it: a partial-silence drill that
  rewrites `response` alone, or a future redaction over just the final
  answer, is not corruption of the conversation record. They agree in the
  ordinary case because whatever recorded a conversation wrote both from
  it; the loader does not require it.
- `FORMAT_VERSION` does not move. A bundle with no multi-turn items reads,
  hashes and scores identically before and after this change; the demo
  bundle's addition of four multi-turn items moved its dataset hash only
  because items were added, the same consequence adding any items has
  always had.

## Consequences

- Every existing bundle, fixture, and consuming repository's evidence
  keeps working with zero changes. This was the deciding property: a
  format-version bump would have made this a breaking change for every
  bundle Plumbline has ever graded, for a capability most of them will
  never use.
- `conversational_integrity` is opt-in twice over: an item must declare
  `turns`, and it must additionally have been *recorded* with a matching
  `turn_responses` — an adapter that has not been taught to keep every
  turn, or a hand-written bundle that only cared about the final answer,
  leaves the suite nothing to check for that item. That item is
  UNVERIFIABLE, never a pass, the same posture `passage_attribution` takes
  on an item with no `answering_sources`.
- No adapter in this repository (`http_json`, `subprocess`) can populate
  `turn_responses` from a live `plumbline record` run yet. Multi-turn
  recording against a real target is out of scope for this change; the
  demo bundle's four multi-turn items are hand-written, the same way the
  rest of the demo corpus is. Teaching an adapter to hold a conversation
  open across turns is a separate, larger decision — likely its own ADR —
  left for whenever a consumer actually needs it.
- A reader of `bundle.py` now has two response surfaces to know about
  (`responses`, `turn_responses`) instead of one, and has to know that the
  suite that reads the second one is the only suite in the harness that
  does. `conversational_integrity.py`'s module docstring and this ADR are
  where that surprise is supposed to land before it lands as confusion.

## Alternatives considered

- **A new item type / format version for conversations.** Rejected: it
  would have forced a migration on every existing bundle for a feature
  most targets will not exercise, and it is more format than the actual
  gap (suites reading only the final turn) needed closing.
- **Enforcing `turn_responses[-1] == response`.** Tried first, reverted
  after `tests/test_fail_closed.py`'s partial-silence drill demonstrated a
  legitimate mutation (rewriting `response` alone) that the check refused
  for no real reason: the two fields are independent evidence, and forcing
  them to agree added a constraint nothing downstream actually needed.
- **Teaching an adapter to record multi-turn conversations against a live
  target in this same change.** Rejected as out of scope: the schema and
  the suite are the gap named in `docs/feature-expansion-ideas.md`; wiring
  a real multi-turn adapter is a separate, larger piece of work with its
  own design questions (how many turns, when to stop, how errors mid-
  conversation are recorded) that do not need to block the schema existing.

## References

- `src/plumbline/bundle.py`, `Item.turns` and `Bundle.turn_responses`.
- `src/plumbline/suites/conversational_integrity.py`, module docstring.
- `docs/feature-expansion-ideas.md`, idea 2.
