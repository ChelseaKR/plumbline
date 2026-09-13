# Feature expansion ideas

This page holds nine proposals for work beyond M9: six have shipped and three
are open. It is a record of ideas and what became of them, so a reader can
tell a considered-but-not-built idea from a considered-and-built one, and so
neither answer has to be taken on trust.

**What this page said until 2026-09-13, and why that is worth leaving on the
record.** It opened: *"None of this is implemented, scheduled, or promised —
it is ideation, dated and attributed like everything else here."* All six
proposals below had already shipped when that sentence was published. They
landed together in [`v0.2.0`](../CHANGELOG.md) on 2026-08-22, as pull
requests #8–#13, and this page went on declaring them unbuilt for
twenty-two days. It
was not a stale figure or a rounding error: it was a claim about the system
with nothing holding it to being true, on the page whose entire purpose is to
tell a reader which is which — the defect this repository exists to argue
against, inside the document that argues it.

Correcting the prose alone would only have reset the clock, so it did not go
in alone. `tools/check_expansion_status.py` now declares, for each proposal
below, the paths that decide its status, and fails in both directions: a
proposal published as shipped whose module is not in the tree, and — the
failure that actually happened — a proposal published as open whose module
*is*. `tests/test_expansion_status.py` proves each of those can go red on a
planted defect rather than only that they pass today. The whole gate is
modelled on `tools/check_claims.py`, which holds the README's and `DESIGN.md`'s
published figures to the committed evidence for the same reason.

Every entry below is anchored to something the repository already says about
itself: a "Not met" cell in the [Standards Conformance](../README.md#standards-conformance)
table, a non-goal it names but does not yet close, or a schema limit visible
in the code. None of the nine proposes a new benchmark, a leaderboard, or a
red-team service — all three stay excluded by the
[Non-goals](../README.md#non-goals) line, and idea 8 below argues explicitly
why measuring the harness's own judge is not the first of them.

Ranked roughly by how directly each closes a gap the project has already put
its own name to. The original six keep their original argument, unedited,
with an outcome added: what shipped, where it lives, what it cost, and what it
promised that is still outstanding.

## What "shipped" was supposed to mean

The closing paragraph of the original page set the terms: if one of these got
picked up it should get the same treatment as M1–M9 — *"a roadmap row in
`DESIGN.md`, a defect-injection case in `proof/matrix.md` before it's trusted,
and — per `docs/adr/0000-record-architecture-decisions.md` — an ADR if
adopting it would be expensive to reverse."* Measured against the tree on
2026-09-13:

- **Roadmap row: all six.** `DESIGN.md`'s **M10** row names every one of them,
  dated 2026-08-22 and marked "beyond spec".
- **Defect-injection case: one of six.** Only idea 2 has a row in
  `proof/matrix.md` (`conversational-integrity-mid-conversation-leak`). Five do
  not, and the reason is structural rather than an oversight for four of them:
  the matrix plants a defect in a copy of the demonstration evidence and runs
  the scoring path, so it can only speak about suites. Signing, SARIF, history
  and the release workflow are not suites and there is nothing for it to score.
  Idea 5 is the exception worth stating plainly — it promised, in its own
  "What's hard" paragraph below, that redaction "needs its own defect-injection
  cases before it earns the same trust the fourteen suites have," and it does
  not have them in `proof/matrix.md`. What it has instead is fourteen
  planted-defect unit tests in `tests/test_retention.py`. That is a real bar
  and it is not the bar the page named.
- **ADR: three of six.** Ideas 1, 2 and 6 have one (`0002`, `0003`, `0001`).
  Ideas 3 and 4 are cheap to reverse — an additive output format and CI wiring
  — and the absence is defensible. Idea 5 is the one where it is not obviously
  defensible: `plumbline retire --redact` rewrites `responses.jsonl` in place
  and re-seals the bundle, which moves the dataset hash and breaks every
  baseline comparison against it. That is evidence being changed on purpose,
  which is the one thing this harness makes structurally hard everywhere else,
  and a decision of that shape is what the ADR log is for.

## 1. Detached report signatures

**Status: shipped** — `src/plumbline/signing.py`, `plumbline sign` and
`plumbline verify --key-file`, ADR
`docs/adr/0002-shared-secret-report-signatures.md`.

**The gap, in the project's own words:** "vouching for who produced a report
would need a signature Plumbline does not issue." The seal in every report
today is tamper *evidence* — it proves a report was not edited after the
run, using a hash with no secret in it. It proves nothing about who ran it.

**The idea:** an optional `plumbline sign` step that produces a detached
signature over the same report body the seal already covers, using a keypair
the operator holds (a raw ed25519 key is enough; no CA, no third-party
runtime dependency, consistent with "no third-party runtime dependency" in
the Security & Supply-Chain row). `plumbline verify` gains a `--pubkey` flag
that checks the signature when one is present and says plainly when one is
not, the same way an unreviewed-translation warning is loud rather than
silent today. Unsigned reports keep working exactly as they do now — this is
additive, matching the existing pattern of `record` and the model judge:
capability that is off unless a config file turns it on.

**Why it fits:** the whole harness is built around the claim that an
unattributed assertion is not evidence. A report that can be tampered-checked
but not attributed to a signer is exactly that kind of half-finished claim,
and the README already names it as one.

**What's hard:** key custody is now the operator's problem, and the harness
would need to say so as plainly as it says gate-offline-forever today, or
this becomes a false sense of authentication.

**What shipped, and the substitution it made.** Not the proposal as written.
The idea asked for a raw ed25519 keypair; what shipped is HMAC-SHA256 over the
report's existing seal, with a shared secret. Public-key signing without a
third-party runtime dependency means hand-rolling asymmetric crypto, which is
exactly the confident-until-it-fails artifact this harness argues against, so
the tradeoff was written down rather than taken quietly:
`docs/adr/0002-shared-secret-report-signatures.md`. The consequence is that
the capability is narrower than the gap it was aimed at — it authenticates
between parties who already share a key, and a reader at large still cannot
attribute a report to anyone. The module and both CLI paths say so in as many
words, and `plumbline verify` says "not checked" out loud when no key is
passed rather than staying silent. `--pubkey` became `--key-file`. Eleven
tests in `tests/test_signing.py`, including a wrong key, an edited signature
file, a signature made for a different report, and a report edited after
signing. **Outstanding:** the original gap — attribution a third party can
verify — is narrowed, not closed, and the README still says so.

## 2. Multi-turn conversation items

**Status: shipped** — `src/plumbline/suites/conversational_integrity.py`, the
fifteenth suite, additive to the bundle format per ADR
`docs/adr/0003-multi-turn-items-are-additive-not-a-new-bundle-format.md`.

**The gap:** `Item` in `bundle.py` is one prompt and one response. Every
suite — `adversarial`, `privacy`, `refusal` included — scores a single turn
in isolation. A target that leaks a system prompt only after three turns of
rapport-building, or that refuses a direct ask but complies when the same ask
is rephrased as a follow-up, is invisible to the current schema no matter how
many suites are enabled.

**The idea:** extend the bundle format to an optional `turns: [...]` list
per item, replacing the single prompt/response pair, with single-turn items
staying valid (a one-element `turns` list, or the current shape treated as
sugar for it — whichever keeps every existing dataset and audit reproducing
byte-for-byte, which `test_self_application.py` and `test_demo_bundle.py`
would need to keep proving). A new suite — `conversational_integrity` or
similar — would score things a single-turn check structurally cannot:
whether a refusal holds under a second attempt in the same conversation,
whether privacy leaks appear only after context accumulates.

**Why it fits:** the project's own defect-injection matrix argues that a
suite is only real once it has been observed catching the defect it exists
for. A multi-turn suite would need its own planted-defect case in
`proof/matrix.md` before it counts, same discipline as the other fourteen.

**What's hard:** this is a schema change, not an additive config flag, so it
touches the adapters, both report formats, the demo-bundle generator, and
every fixture. It's the largest of the six.

**What shipped.** The largest of the six, and the only one that met every term
the page set. `Item.turns` and a response record's `turn_responses` are
additive fields rather than a replacement for `prompt`/`response`: an empty
`turns` list is byte-identical to every item this harness had ever loaded and
`FORMAT_VERSION` did not move, which is why ADR 0003 exists — a new bundle
format would have been expensive to reverse and this deliberately is not one.
Opt-in twice over: an item declares `turns` *and* was recorded per turn, or it
is UNVERIFIABLE, never a pass. The demo bundle grew from 174 to 178 items with
four hand-written escalation probes. It earned its
`proof/matrix.md` row — `conversational-integrity-mid-conversation-leak`, a
probe that leaks on the escalation turn and then produces a clean final answer
— and `tests/test_conversational_integrity.py` asserts directly that no other
suite catches that same fixture. **Outstanding:** at four multi-turn items it
is the one under-powered suite in the harness; the README states its n and its
MDE next to every other suite's band rather than letting the number pass
unremarked.

## 3. Machine-readable findings for consuming PRs

**Status: shipped** — `src/plumbline/sarif.py`, `--sarif` on `audit` and
`gate`. No ADR, and none was needed.

**The gap:** both real consumers — `cairn` and `fare-policy-assistant` —
pin the harness and run it on every pull request, and neither makes it a
required check yet; the harness "reports rather than blocks." A human still
has to open the Markdown report to see which item failed and why.

**The idea:** a report exporter (`plumbline gate --annotations sarif`, or a
`plumbline report --format sarif`) that emits SARIF alongside the existing
JSON and Markdown, so a consuming repo's CI can turn a failing item into an
inline PR annotation the way a linter finding shows up today. The per-item
records already carry a suite name, an item id, and a verdict — SARIF is a
projection of data the report already has, not a new measurement.

**Why it fits:** it moves the two real consumers closer to using the gate as
something other than a report nobody opens, without touching what gets
measured or how — the fail-closed exit-code contract stays exactly as it is,
and a target that returns nothing still fails the way it fails today.

**What's hard:** SARIF has its own schema opinions about "rules" and
"locations" that map awkwardly onto a scoring suite rather than a linter;
getting the shape right without overclaiming precision (a suite score is not
a line number) needs care.

**What shipped.** SARIF 2.1.0, as a flag rather than a subcommand, written
only when asked for. The schema problem the page anticipated was resolved by
refusing the tempting answer: every result carries a *logical* location — the
item id, or the suite's own identifier for a fact pair or a structural check —
and never a fabricated line number, because a suite score is not a line and
inventing one would buy inline annotations at the price of an overclaim. The
cost is stated where a consumer will hit it: tooling that expects a physical
location gets the finding in GitHub's Security tab and not in the diff. Only
failing and UNVERIFIABLE records become results; a passing item is not a
finding, the same way a clean lint pass emits nothing. Nothing about scoring
or the exit-code contract moved. **Outstanding:** the reason the gap existed
is still there — neither consumer has made the gate a required check, and a
better-rendered finding is not the same as a blocking one.

## 4. Supply-chain closure: SBOM, Scorecard, signed release

**Status: shipped** — `sbom.cdx.json` built by `tools/build_sbom.py`,
`.github/workflows/release.yml`, `.github/workflows/scorecard.yml`, and
`.github/workflows/publish-pypi.yml`. No ADR, and none was needed.

**The gap:** two rows in the Standards Conformance table name the same
family of missing artifacts — "no SBOM, no OpenSSF Scorecard, no signed
release" (Security & Supply-Chain) and "no release workflow, no signed tag,
no published artifact" (Release & Versioning). The harness already has the
best possible starting position for this — zero third-party runtime
dependencies — so closing it is mostly wiring, not redesign.

**The idea:** a release workflow that runs on a tag, generates a CycloneDX
or SPDX SBOM from `uv.lock` (which is small, since the runtime dependency
list is empty), submits to OpenSSF Scorecard, and signs the tag and the
published artifact — Sigstore's keyless `cosign` flow fits the project's
existing aversion to committing secrets, and composes with idea #1 if that
ships first.

**Why it fits:** this is the one idea on the list that adds no measurement
surface at all — it only makes true a set of claims the README already
scores itself against and currently marks "not met." It is the most
mechanical of the six and the least likely to need a design discussion.

**What's hard:** none of it technically, but it is recurring maintenance
(Scorecard results drift, signing keys rotate) rather than a one-time build,
which is a different kind of commitment than the rest of this list.

**What shipped, and what it cost to find out.** A CycloneDX SBOM generated
from `pyproject.toml` rather than `uv.lock`, checked for staleness the same
way the published page is, and keyless-signed with Sigstore cosign on a `v*`
tag. Scorecard could not live in the release workflow at all — the action
refuses anything but the default branch — so it is `scorecard.yml`, on push to
`main` and weekly. "The most mechanical of the six" was right about the design
and wrong about the cost: the first real tag push found two defects a green
workflow file had been hiding, a 39-character `actions/upload-artifact` pin
that could not resolve and the Scorecard job that could never run, and both
are in the CHANGELOG. A `verify-tag` job was added later still, gating both
publishing paths on an annotated tag whose SSH signature verifies against a
committed allowed-signers file, with `tests/test_release_tag_gate.py` running
it against unsigned, lightweight, wrong-key, absent and wrong-commit tags
rather than only a good one. **Outstanding:** first observed Scorecard score
6.1/10, with SAST at 0 because Scorecard does not credit the Semgrep and
TruffleHog jobs that do run; `v0.1.0` predates the workflow and `v0.2.0` was
cut with `git tag -a` rather than `-s`, so it sits in a grandfather list and
its signature is not checked. The recurring-maintenance warning this paragraph
made about itself is the part that stays true.

## 5. Recording retention and redaction lifecycle

**Status: shipped** — `src/plumbline/retention.py`, `plumbline retire`, and
the data card at `docs/recordings-data-card.md`. No ADR, and this is the one
where its absence is arguable.

**The gap:** "no data card and no stated retention position for recordings,
which the `.gitignore` keeps out of the repository but does not otherwise
govern" (Data Governance row). `plumbline record` captures live-target
transcripts against real question sets; for a harness whose entire subject
is government-facing chat, those transcripts are exactly the kind of
artifact that could carry the personal data the `privacy` suite exists to
screen for in the *target's* answers, sitting unmanaged on the operator's
disk.

**The idea:** a companion command — `plumbline retire` — that runs the same
privacy screen already used for scoring against a recording directory, and
either redacts flagged spans in place or refuses to leave the recording
unredacted past a configured age, the same fail-closed posture as the gate
itself: silence about a retention policy is not a retention policy, echoing
"silence is never evidence." Ships with a short data card describing what a
recording contains and what governs its lifetime, closing the "no data card"
half of the gap in the same change.

**Why it fits:** it reuses scoring logic that already exists (`privacy.py`)
for a governance purpose instead of a grading one — the same asymmetry the
project already draws between `smoke` (did it answer) and the harm suites
(did it answer badly), applied to the harness's own output instead of the
target's.

**What's hard:** a redaction tool that is wrong in either direction is worse
than none — over-redact and the recording stops being useful evidence for a
re-run; under-redact and the retention promise is false. This needs its own
defect-injection cases before it earns the same trust the fourteen suites
have.

**What shipped, and the bar it did not meet.** `plumbline retire` reuses
`judges.LexicalJudge.pii_in` — the same primitive `privacy.py` scores with,
not a second screen that could drift from it — and refuses outright past the
configured window when a pattern still matches and redaction was not asked
for. Redaction rewrites `responses.jsonl` and re-seals the bundle, which is
the only legitimate way to change evidence here and is also why the dataset
hash moves and every baseline comparison against that recording breaks. The
data card shipped with it and says, in the place a reader looking for a
retention policy would look first, that a clean screen means no shipped
pattern matched and not that no personal data remains. **Outstanding, and it
is the promise this page made:** the defect-injection cases named above are
not in `proof/matrix.md`. `tests/test_retention.py` has fourteen tests
including planted identifiers on both sides of the window, which is a real bar
and a different one. Separately, the README's Data Governance row still reads
"Not met" for three reasons this change did not touch — no real recording
exists to apply it to, the screen finds identifiers rather than judgment
calls, and no jurisdictional retention requirement is mapped to a default
`--max-age-days`. And a command that rewrites sealed evidence in place is the
kind of decision ADR 0000 exists for; it does not have one.

## 6. Longitudinal run history, not just one stored baseline

**Status: shipped** — `src/plumbline/history.py`, `plumbline history append`
and `plumbline history check`, ADR
`docs/adr/0001-longitudinal-history-is-observation-not-inference.md`.

**The gap:** `baseline.py` compares a run against exactly one stored
baseline, refusing the comparison outright across a changed dataset or judge
hash. That is deliberately conservative and correct for what it does. It
also means a slow drift — a suite creeping downward by less than one
baseline's MDE on each individual run — never accumulates into anything
visible, because each comparison is evaluated in isolation against the same
fixed point. The Observability row separately notes "no operations
runbook": there is no answer today to "how has this target trended over the
last twenty runs."

**The idea:** an append-only, content-addressed run history
(`plumbline history` reading a directory of past reports, keyed the way
`audits/<run-id>/` already is) that plots or tables each suite's score
across successive runs sharing a dataset and judge hash, flagging a
monotonic decline across N runs even when no single step exceeds that
suite's MDE. This does not replace the existing pairwise baseline
comparison or loosen its refusal rules — a differing dataset or judge hash
still breaks the chain the same way it breaks a pairwise comparison today —
it adds a second, longer-window view on top.

**Why it fits:** it is the direct generalization of a mechanism that already
exists and is trusted (baseline regression, MDE-qualified deltas) rather
than a new statistical claim, and it gives the two pinning consumers
something to look at between gate runs instead of only at gate-failure time.

**What's hard:** the MDE discipline that makes single-pair comparisons
defensible does not obviously generalize to "N points trending down" without
either a stricter test (more false negatives) or a real trend statistic
(more machinery than this project has needed anywhere else so far) — this
is the one idea here that risks adding an assertion the harness cannot yet
back with the same rigor as its other numbers.

**What shipped, and how the hard part was answered.** By declining it. ADR
0001 records the decision: the history reports an observation, not a
statistic. It computes no interval and no p-value of its own; it reports one
plain structural fact — whether a suite declined on every one of the last N
comparable runs — which a reader can check by eye against the numbers printed
beside it. An append-only file rather than the directory scan the idea
proposed, because reports carry no timestamps by design and directory
modification times change on a checkout or a rebase: the order entries were
appended, visible in the git history of the committed history file, is the
only timeline this has. **Outstanding:** the risk named above was avoided
rather than solved. A drift slower than a decline on *every* run is still
invisible, and the honest answer to "how has this target trended" is still
"here are the numbers, look at them," not a statistic.

---

## Open ideas: what replaces them

Three proposals, none of them built, written 2026-09-13 against the state of
the tree that day. They replace the six above, which are spent. Each is
anchored the same way: a "Not met" cell the README already writes against
itself, or a gap a document in this repository names in its own words. None
of them proposes a new benchmark, a leaderboard, or a red-team service.

Ranked, again, by how directly each closes a gap the project has already put
its own name to.

## 7. A committed required-checks contract

**Status: open** — nothing at `.github/required-checks.json`, nothing at
`tools/check_required_checks.py`.

**The gap, in the project's own words:** the CI/CD conformance row, after
correcting itself once already about what protects `main`, ends: *"Not met: no
ruleset file is committed, so the seven required contexts live only in a
settings page nobody can diff, and a renamed job would silently stop being
required with nothing in the tree to notice."* The seven are `tests (3.11)`
through `tests (3.14)`, `quality`, `SAST (semgrep)` and `full-history secret
scan (verified only)`, under classic branch protection with
`enforce_admins: true` and no break-glass path.

**The idea:** commit the seven context names as data, and hold the workflows
to them. A checker walks every workflow in `.github/workflows/`, resolves what
job names each one actually produces — including the matrix expansion that
turns one `tests` job into four contexts — and fails when a required context
names a job no workflow produces, or when a job that a required context names
has been renamed. Wired into `make verify`, so the failure arrives on the
branch that renames the job rather than on the pull request that waits forever
for a check which can never report.

**Why it fits:** the tree already contains exactly one instance of this check,
hand-written, covering one context of seven. `tests/test_secret_scanning.py`
holds the secret-scanning job to the exact name branch protection requires,
and the workflow carries a comment explaining why it will not be renamed for
accuracy's sake — "renaming it here would retire the context the protection
requires and leave every future pull request waiting on a check that can never
report." One assertion covering one seventh of the surface is the same shape
as `CONTRAST_PAIRS` before `palette_coverage`: a real check that reports clean
over everything it was never pointed at. This generalizes it, and does it the
way this repository does everything else — as data plus a checker that can go
red, not as a comment.

**What's hard:** the committed file would be a mirror, not the source of
truth. GitHub's settings page still decides what blocks a merge, and a
committed list that has drifted from the real protection is a second claim
with nothing behind it — the original defect wearing a fresh coat. Closing
that honestly needs either a reconciliation step against
`gh api .../branches/main/protection`, which is a network call every local gate
here refuses to make and which needs a token, or a plainly stated scope: this
file is a diffable declaration of intent, checked against the workflows and
not against GitHub. The second is cheap and half the value; deciding which one
is being bought is the actual work, and it is the kind of decision ADR 0000
exists for.

## 8. A human-adjudicated sample for the model judge

**Status: open** — nothing at `datasets/judge-agreement/`, nothing at
`tools/judge_agreement.py`.

**The gap, in the project's own words:** the AI Evaluation conformance row is
otherwise the strongest in the table, and ends: *"Not met: the card names its
own biggest gap — nothing measures how often the model judge agrees with a
human rater."* `docs/model-card-judge.md` says the same thing about itself.
The optional model judge is off by default, refused outright by `gate`, and
taints the run id so differently-judged runs cannot compare as equal — every
one of those is a guard against trusting it, and none of them is a
measurement of it.

**The idea:** a small committed adjudication set — items drawn from the
demonstration bundle, each carrying a verdict a person wrote down by hand,
attributed and dated the way every other artifact here is — and a tool that
reports, per suite, how often the default lexical judge and the optional model
judge agree with those verdicts, and enumerates every disagreement. Publish
the disagreement *list*, not only a rate: this repository's own argument is
that a percentage with no reproducible case behind it is the thing to distrust,
and a named item a human and a judge scored differently is something the next
person can go and read.

**Why it fits, and why it is not the benchmark the non-goals exclude:** a
benchmark scores targets, and a leaderboard ranks them. This scores neither. It
points the instrument at itself, which is the move this repository has already
made everywhere else — the defect matrix is the harness grading its own suites,
`tools/check_site_a11y.py` holds the published page to the standard the
`accessibility` suite holds a target's interface to, and this change's own
`check_expansion_status.py` holds this page to the tree. A judge nobody has
measured against a person is the last unmeasured instrument in the box.

**What's hard:** one rater is not agreement, it is one person's opinion written
down, and a single-labeller number published as "agreement" would be precisely
the overclaim the model card warns about. Doing it honestly needs at least two
independent labellers, a written adjudication procedure for the cases they
split on, and the inter-rater number published alongside the judge number so a
reader can see which of the two is the noisier instrument. And the demonstration
bundle is synthetic: agreement measured on it is a fact about the judge's
behaviour on invented text, and the card would have to say so as loudly as it
says everything else — the same limit `docs/first-real-target.md` already names
for the harness as a whole.

## 9. A staleness gate for the two documents nothing holds

**Status: open** — nothing at `tools/check_ledger_freshness.py`.

**The gap, in the project's own words:** the Quality & Metrics row closed two
gaps it had named against itself and left a third open in the same sentence:
*"Not met: nothing enforces that either document actually gets kept up to date;
both name that against themselves."* `docs/metrics-ledger.md` is blunter about
it: *"This ledger is hand-maintained. Nothing enforces that a row gets added
... a ledger nobody is reminded to update decays the same way an unscheduled
retention sweep does."*

**The idea:** recompute the metrics the ledger's own "what each column means"
section already gives a command for — registered suite classes, discovered
tests, branch coverage, `make lint`'s ruff findings, functions over McCabe
complexity 10, mypy — and fail when today's tree disagrees with the newest row
and no newer row has been appended. Not a reminder and not a checklist item: a
red step, which is the only kind this repository considers real. The ledger's
append-only rule is part of the contract the gate enforces, so a disagreement
can only be settled by adding a row, never by editing the last one.

**Why it fits:** it is the same shape as `tools/check_claims.py` and as the
gate this very change ships — a document that names a gap against itself, with
nothing behind the naming. `docs/definition-of-done.md` already carries "has a
new row, if the change moved any metric it tracks" as a checklist item and says
in its own closing section that turning its mechanical items into a script is
"a reasonable next step, not a promise this document is making." This is that
step, for the one item on the list that is a pure computation.

**What's hard:** not every column is a function of the tree. The ledger's own
2026-08-29 row exists because a ruff upgrade moved the wide-rule finding count
on code that had not changed, and nothing recorded at the time could separate
the tool from the repository. A gate that went red on that would fail on a
Dependabot bump and teach people to append a row to silence it — the badge,
one level in. The honest scope is the subset that is deterministic given a
pinned tool version (suite count, test count, complexity) plus an explicit
statement that the rest stays hand-maintained and why — which closes part of
the named gap and has to say which part, the same way every "Not met" row here
already does.
