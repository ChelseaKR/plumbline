# 0004. Unscored suites are disclosed in every report, never enforced

- Status: Accepted
- Date: 2026-08-27

## Context

A Plumbline report has always listed the suites that ran. It has never
listed the suites that did not, and the two are not the same disclosure.

[`docs/responsible-tech.md`](../responsible-tech.md) names the gap in its
own words, twice. As a residual risk:

> **A suite that was never enabled catches nothing, and a `PASS` does not
> say which suites ran.** [...] A target that never enables `privacy` or
> `adversarial` can pass every suite it did enable while leaking personal
> data or complying with every injection attempt, and nothing about the
> word "PASS" on its own discloses that.

And as a misuse the repository can name but not prevent:

> **Selective suite enablement as a quiet way to avoid a hard question.**
> Enabling `smoke` and `accuracy` while leaving `adversarial` and `privacy`
> off is a valid configuration and a legitimate way to phase in coverage —
> and an easy way to produce a clean-looking report about a system nobody
> checked for the things those two suites exist to check. The same
> suite-list discipline above is the only defense named in this document.

"Read a verdict together with the suite list it came from, every time" is
a real instruction and a weak control. It asks a reader to notice an
*absence* in a fourteen-row table, which requires knowing the registry by
heart, and it asks it of the reader least likely to be holding the table:
the one reading a `PASS` in a build log, a status update, or a slide.

Two adjacent defects made the same class of problem worse, and both are
fixed in the change this ADR accompanies. A key inside `[suites.<id>]`
that this harness does not read — `flooor = 0.99` — was silently ignored
by TOML, and the suite then ran at the harness's *demonstration* default
(0.75) rather than at the number the reviewable file appears to set. And
`enabled` accepted any truthy value, so `enabled = 0` switched a suite off
without a word and `enabled = "false"` left it on.

## Decision

Every report carries a `scope` block, built by `src/plumbline/scope.py`,
naming every **implemented** suite the run did not score and which of two
reasons applies: `absent` (the configuration never mentions it) or
`disabled` (the configuration names it and sets `enabled = false`). It is
rendered as a `## Scope` section in the Markdown report and as one line on
the terminal, from both `plumbline audit` and `plumbline gate`.

**The block never affects the verdict.** A partial configuration is not a
defect and is not refused.

Three properties are deliberate:

1. **The section renders even when nothing is missing.** A section that
   appeared only on a partial configuration would teach a reader to read
   its absence as full coverage, which is the same mistake in the other
   direction, and this repository does not accept an absent warning as
   evidence anywhere else.
2. **The denominator is derived from the suite registry**, not written
   out. A suite added later is counted without anyone remembering to
   update a literal, which is how a disclosure like this silently starts
   under-reporting. `tests/test_scope.py` pins it against
   `suites.available()`.
3. **It is inside the sealed report body**, so a scope claim cannot be
   edited off a written report without `plumbline verify` refusing it.

Separately, and so that the floors the block reports are the floors the
file states: an unknown key in a `[suites.<id>]` table is a configuration
error, and `enabled` must be a real boolean.

## Consequences

- A `PASS` reaching a reader through the build log now arrives with the
  omission attached: `scope: 12 of 15 implemented suites scored; NOT
  scored: adversarial (absent), privacy (absent), refusal (disabled)`.
- The report grows a top-level key. Every committed report, baseline,
  proof matrix and published page is regenerated for it, as any change to
  the report shape requires.
- Configurations that were silently running a weaker gate than they state
  now fail to load. That is a breaking change for those configurations,
  and it is the point: the alternative is a gate that disagrees with its
  own reviewable file. `CHANGELOG.md` records it as such.
- `scope.py` has to be kept honest about *why* a suite did not run. Two
  reasons is the whole space today because `config.load_config` refuses
  everything else — an unknown suite id, a skeleton, a floor outside
  `[0, 1]`, a floor of zero — before a run reaches this code.

## Alternatives considered

**Fail the gate on a partial configuration.** Rejected. It would refuse
the legitimate case, phasing coverage in, along with the evasive one, and
the harness cannot tell them apart. It also contradicts a position this
repository has already taken in writing: "Nothing in this harness
second-guesses a floor a human committed to a reviewable file. The review
is the safeguard; a harness cannot supply the judgment a floor
represents." The same sentence applies to a suite list.

**A `--require-all-suites` flag, or a `[suites].required` list.**
Rejected for now, not on principle. It is a real option and a small one,
but it puts the policy back in the same file the policy is being evaded
in, so it protects against forgetting rather than against choosing. The
disclosure is what a *reviewer* needs, and the reviewer is the control
this repository has already named. If a consumer asks for the flag later,
this ADR is not in its way.

**Emit it as a warning instead of a report section.** Rejected. Warnings
in this harness are for things that happened during a run — an unreviewed
translation, a model judge. A suite list is a property of the
configuration, is true of every run under that configuration, and belongs
next to the suite table it completes rather than in a channel a reader
learns to skim.

**A defect-injection case in `proof/matrix.md`.** Rejected as the wrong
home. Every case in that matrix plants a defect in the *evidence* — "a
defect in the system under test, arriving through the front door", in
`tools/defect_matrix.py`'s own words. A configuration that omits a suite
is not a defect in the target; it is a property of the gate. The proof
lives in `tests/test_scope.py` and, for the two configuration refusals, in
`tests/test_fail_closed.py`, which is where this repository already keeps
"a check that could not fail".

## References

- `src/plumbline/scope.py`, `src/plumbline/config.py`
- `tests/test_scope.py`, `tests/test_fail_closed.py`
  (`AMisspelledKeyIsNotAConfiguredFloor`)
- [`docs/responsible-tech.md`](../responsible-tech.md), "Residual risks"
  and "Misuse this repository can name but not prevent"
- [ADR 0001](0001-longitudinal-history-is-observation-not-inference.md),
  for the same posture applied to trend reporting: report the structural
  fact, do not manufacture a judgment the data cannot carry
