# Feature expansion ideas

Six proposals for work beyond M9. None of this is implemented, scheduled, or
promised — it is ideation, dated and attributed like everything else here, so
a reader can tell a considered-but-not-built idea from a considered-and-built
one. Every entry below is anchored to something the repository already says
about itself: a "Not met" cell in the Standards Conformance table, a
non-goal it names but does not yet close, or a schema limit visible in the
code. None of the six proposes a new benchmark, a leaderboard, or a red-team
service — all three stay excluded by the [Non-goals](../README.md#non-goals)
line.

Ranked roughly by how directly each closes a gap the project has already put
its own name to.

## 1. Detached report signatures

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

## 2. Multi-turn conversation items

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

## 3. Machine-readable findings for consuming PRs

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

## 4. Supply-chain closure: SBOM, Scorecard, signed release

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

## 5. Recording retention and redaction lifecycle

**The gap:** "no data card and no stated retention position for recordings,
which the `.gitignore` keeps out of the repository but does not otherwise
govern" (Data Governance row). `plumbline record` captures live-target
transcripts against real question sets; for a harness whose entire subject
is government-facing chat, those transcripts are exactly the kind of
artifact that could carry the personal data the `privacy` suite exists to
screen for the *target's* answers, sitting unmanaged on the operator's disk.

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

## 6. Longitudinal run history, not just one stored baseline

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

---

None of the six is scoped to a milestone. If one gets picked up, it should
get the same treatment as M1–M9: a roadmap row in `DESIGN.md`, a
defect-injection case in `proof/matrix.md` before it's trusted, and — per
`docs/adr/0000-record-architecture-decisions.md` — an ADR if adopting it
would be expensive to reverse.
