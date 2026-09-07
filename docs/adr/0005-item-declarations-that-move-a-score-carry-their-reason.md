# 0005. An item declaration that moves a score is additive, carries its reason, and exempts nothing from a screen

- Status: Accepted
- Date: 2026-09-07

## Context

Two consumer findings arrived with the same shape: a correct behaviour and an
incorrect one were coming out of this harness as the same number, so the score
could not tell them apart and the item could not ship.

**Cross-language answering.** A consumer's corpus for one jurisdiction is
English-only. Their product answers an Arabic question by quoting the English
passage verbatim under an Arabic notice saying that is what it did. That is the
right behaviour for that corpus, and `multilingual` scored it `0.0000` — the
same number a system that simply ignored the question's language gets. Their
evidence set has a one-item ceiling for that reason: a second such item turns
the gate red.

**A tool's own voice.** The same consumer's table tool prefixes its answer with
a notice in its own voice. A lexical support metric marks the notice
unsupported, because nothing in the sources says it, so a correct disclosure
scores as a fabrication.

In both cases the harness has no way to tell which of two opposite things it is
looking at, and this harness does not guess. Only the dataset can say. The
question this ADR settles is what a dataset saying so may cost, because a field
that lets a declaration override a measurement is the one kind of field that
can turn this instrument into a way of buying a pass.

ADR 0003 settled the same question for `turns` and reached "additive fields,
not a new format". This extends that answer and adds two constraints it did not
need.

## Decision

Two opt-in item fields, additive to bundle v1 exactly as ADR 0003 defines
additive, under three rules.

**1. Additive, and `FORMAT_VERSION` does not move.**

- `Item.expected_response_lang: {"lang": str, "reason": str} | None` — the
  language this item's answer is supposed to come back in, when that is not the
  language the question was written in. `multilingual` scores against it
  instead of `Item.lang`; nothing else reads it.
- `Item.target_voice: list[str]`, defaulting to empty — literal strings the
  target emits in its own voice. `Bundle.answer_text_for` removes them, and
  `groundedness`, `citation_accuracy` and `passage_attribution` read that
  instead of the raw response.

A bundle declaring neither reads, hashes and scores identically. That is
checked rather than asserted: regenerating the 178-item demo audit, which
declares neither, moved no score, no floor, no verdict, no `n` and no interval
— only `harness_source_sha256`, the report seal derived from it, and the
harness-differs caveat, which any edit under `src/plumbline/` moves.

**2. A declaration that moves a score carries its reason, and the report says
how much rests on one.**

`expected_response_lang` requires a non-blank `reason`, and the item record
publishes it. Every suite that reads a declaration publishes the ids of the
items that made one, and `report._declaration_lines` prints, per suite, how
many of its items were scored under one. A reader who cannot separate the
measured part of a score from the declared part is reading two different things
added together.

Two refusals follow from the same principle. `expected_response_lang.lang ==
item.lang` is a bundle error rather than a no-op: it declares nothing, changes
no score, and would read to anyone auditing the bundle as a reviewed decision
about a cross-language answer that nobody took. An unrecognised key inside the
declaration is refused rather than ignored, because a misspelt field that was
silently dropped leaves the bundle saying on its face that it declared
something it did not.

**3. A declaration exempts text from the measures, never from the screens.**

This is the load-bearing half, and it is not a preference.

`target_voice` removes text from the three suites that ask *what the sources
support*. It does not, and must not, reach `privacy`,
`representational_harms` or `adversarial`, all of which keep reading
`bundle.response_for` and see every response whole. A notice is the target
speaking. A target that leaks personal data, produces a harm, or complies with
an injection while speaking in its own voice has still leaked, harmed and
complied — and a declaration that could hide that would be a way to buy a pass
by declaring the sentence that fails.

`proof/matrix.md` carries a case that plants exactly that: a probe extracts the
system prompt and the bundle declares the leaked sentence as the target's own
voice. `adversarial`, `representational_harms` and `privacy` all still fail.

## Consequences

An item may now be scored against something the dataset asserted rather than
something this harness measured, which is new, and the mitigation is disclosure
rather than prohibition: the reason is required, the ids are published, and the
report counts them. That is the same treatment `answering_sources` already gets
in `passage_attribution`, and for the same reason — only the dataset can say
which passage answers a question, or which language an answer was meant to be
in.

The exemption boundary is now a property somebody could get wrong in one line,
by "helpfully" routing a screen through `answer_text_for`. It is held by a test
per screen and by a matrix case, and a negative control confirms that pointing
`adversarial` at `answer_text_for` turns those tests red.

`target_voice` matches literally and repeatedly, never as a pattern. A
declaration that quietly matched more than it said would be a way to hide an
answer's own sentences from the measure, and a fuzzy match is not something a
reader of the bundle could check.

Deliberately not decided here: the `notice` response field the original
proposal offered as an alternative source for the same exclusion. Nothing that
records a response can populate it today, so shipping it would be adding a
field a bundle author cannot fill and a consumer cannot produce. It belongs
with the adapter work, not with the declaration.
