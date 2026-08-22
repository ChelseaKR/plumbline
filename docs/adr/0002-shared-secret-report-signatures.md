# 0002. Report signatures are shared-secret, not public-key

- Status: Accepted
- Date: 2026-08-22

## Context

Every report carries `report_sha256`: a plain sha256 over the report's own
body, with no secret in it. `plumbline verify` already states its limit in
as many words — "this is tamper evidence, not authentication ... vouching
for WHO produced a report needs a signature over these bytes, which
Plumbline does not issue." A reader who needs to know who ran a report,
not only whether it was edited afterward, has had no way to get that from
the tool.

The word "signature" ordinarily implies a public-key guarantee: anyone can
verify, only the holder of a private key can produce. Building that
honestly needs either an asymmetric-crypto implementation — ed25519 or RSA
— written from the standard library's primitives, or a third-party runtime
dependency that provides one.

## Decision

Ship neither. `signing.py` implements HMAC-SHA256 over a report's own seal,
using a shared secret the signer and every intended verifier hold — stdlib
`hmac`, nothing else. `plumbline sign --key-file` writes a detached
`report.sig`; `plumbline verify --key-file` checks it.

The module documents its own limit at the top, in the same voice the rest
of the harness uses for what a measurement does not prove: this is
authentication between parties who already share a secret, not a public
attestation. A reader without the key learns only that a signature exists
and which key id it names, never anything about who is right.

### Why not hand-rolled asymmetric crypto

Ed25519 and RSA are not exotic algorithms, and Python's own standard
library ships neither a general-purpose asymmetric-signature primitive nor
the modular-arithmetic building blocks to implement one safely (constant-time
scalar multiplication, safe curve arithmetic, side-channel resistance). A
harness that argues, at length, that a check nobody can verify is worse than
no check would be shipping exactly that kind of artifact: a homemade
signature scheme nobody outside this repository has reviewed, protecting a
claim ("this report is authentic") stronger than the tamper evidence it
replaces. `pyproject.toml`'s own reasoning for leaving the wider ruff rule
set unconfigured — "pretending otherwise... would be the badge this
repository exists to argue against" — is the same reasoning here, applied to
cryptography instead of lint findings.

### Why not a third-party dependency

The Security & Supply-Chain conformance row states the tradeoff plainly:
"no third-party runtime dependency, so the largest supply-chain surface does
not exist here." Adding `cryptography` or a similar package for one feature
would be the first runtime dependency this harness has ever taken on, for a
capability most consumers running an offline, deterministic gate will never
invoke. If a future consumer genuinely needs public-key attestation this
harness cannot honestly provide without a dependency, that is a decision for
its own ADR, made deliberately, not one this feature should back into.

## Consequences

- A report can now be attributed to a signer, but only among people who
  already hold the same key — a private-team or internal-CI use case, not a
  public one. Key distribution and rotation are the operator's problem, and
  `signing.py`'s docstring says so.
- `key_id` (a short sha256 fingerprint of the key) lets a reader confirm
  which key was used without exposing it, so a signature can at least be
  attributed to "whichever run has this key id" across many signed reports,
  even by a party who does not hold the key.
- If a real need for public verification without a shared secret emerges,
  the honest answer is a dependency and a new ADR, not stretching HMAC past
  what it can prove or rolling asymmetric crypto in-house.

## Alternatives considered

- **Ed25519 via a hand-rolled implementation.** Rejected: the risk of a
  subtly wrong implementation is exactly the failure mode this project
  spends the most words arguing against elsewhere.
- **A third-party dependency (e.g. `cryptography`, `PyNaCl`).** Rejected for
  now: the harness's zero-runtime-dependency posture is load-bearing for the
  Security & Supply-Chain conformance row, and this is the only feature that
  would need one.
- **No signing feature at all.** Rejected: the gap is real and the README
  already names it; a shared-secret signature is a genuine, honestly-stated
  improvement over "no attribution mechanism at all," even though it is not
  the strongest attribution mechanism that exists.

## References

- `src/plumbline/signing.py`, module docstring.
- `docs/feature-expansion-ideas.md`, idea 1.
