# 0006. Proposal: asymmetric report signing for attestations a stranger can verify

- Status: Proposed. Nothing in this record is implemented, and no code changes
  with it.
- Date: 2026-10-17
- Relates to: [0002](0002-shared-secret-report-signatures.md). This proposal
  does not supersede 0002. If accepted, it adds a second signature algorithm
  beside HMAC; 0002 would be marked superseded only if HMAC were later removed.

## Context

`plumbline sign` writes a detached HMAC-SHA256 signature over a report's seal.
ADR 0002 chose that deliberately, and named its limit: the verifier must hold the
same secret as the signer, so it works between parties who already trust each
other and distribute a key out of band. It cannot support a verifier who has
never met the signer. Anyone holding the key can also produce a signature, so a
valid HMAC proves "someone with the key" and not "the named party".

ADR 0002 also said what the honest path forward would be: a dependency and a new
ADR, "made deliberately". This is that ADR, written as a proposal so the choice
can be argued before any code exists.

The case it addresses is narrow. A report is produced by one party and handed to
another who must decide whether it really came from the first, without sharing a
secret with them. Examples are a report attached to a review, or a report a
maintainer publishes next to a release. Reports that stay inside one team are
already served by HMAC.

Two constraints from the rest of the repository:

- **No third-party runtime dependency.** The Security & Supply-Chain row depends
  on it, and `sbom.cdx.json` declares it. The standard library provides no
  Ed25519 or RSA signing primitive, so an in-process implementation would mean
  either writing one (rejected in 0002, still rejected) or importing a package.
- **Fail closed.** A signature that cannot be checked is not a signature that
  passed. The existing `UNVERIFIABLE` discipline applies: absence of a check is
  reported as absence, never folded into a pass.

## Proposal

Keep the signed message exactly as it is today: the report's own seal digest,
which `verify_report` already recomputes and refuses to sign if it does not
match. Add a second family of detached signatures over that same digest, produced
and checked by tools that already implement the cryptography, called across a
process boundary rather than imported. The runtime stays dependency-free.

### Backend A: OpenSSH signatures (Ed25519), the default proposal

`ssh-keygen -Y sign` and `ssh-keygen -Y verify` implement SSHSIG, which supports
Ed25519 keys, a namespace string that separates uses of a key, and an
allowed-signers file mapping principals to public keys.

This repository already relies on exactly this mechanism for release tags:
`.github/verify-release-tag.sh` verifies tag signatures against the committed
`.github/allowed_signers`. Reusing it adds no new trust root, no new tool for the
maintainer to learn, and no new category of failure.

- Namespace: `plumbline-report@v1`, so a key used for tags cannot be replayed as
  a report signature or the reverse.
- Signed bytes: the ASCII seal digest, prefixed with a fixed domain-separation
  line, the same pattern the HMAC path uses.
- Trust: the verifier supplies an allowed-signers file and a principal. Plumbline
  never decides whom to trust.

### Backend B: Sigstore keyless, for reports produced in CI

`cosign sign-blob --bundle` signs with a short-lived certificate bound to an OIDC
identity, and `cosign verify-blob` checks the bundle against an expected
identity and issuer. The release workflow already uses this for the SBOM. The
benefit over a long-lived key is that there is no key to custody or rotate and a
transparency-log entry gives the signature a verifiable time. The cost is that it
needs an OIDC identity at signing time and network access to verify unless the
trusted root is supplied offline.

Backend B is optional within this proposal. If only one backend is accepted it
should be A.

### Signature file

The existing file is `report.sig` with `format: plumbline-signature` and an
`algorithm` field. A new `algorithm` value selects the family
(`ssh-ed25519-sshsig` or `sigstore-bundle`), with the SSHSIG armor or the
Sigstore bundle embedded as a string. HMAC signatures stay valid and unchanged.

### Command line

```
plumbline sign   report.json --ssh-key ~/.ssh/plumbline_ed25519
plumbline verify report.json --allowed-signers signers --principal NAME
plumbline verify report.json --require-algorithm ssh-ed25519-sshsig
```

`--require-algorithm` exists to prevent downgrade. Without it, a verifier handed
a report with an HMAC signature attached would accept whichever algorithm the
file names, and an attacker who cannot forge an asymmetric signature could swap
in one the verifier cannot meaningfully check. A verifier that needs an
asymmetric attestation says so, and anything else fails.

## What this would and would not prove

It would prove that the holder of a specific private key, or the holder of a
specific OIDC identity, signed this exact report seal, and that the report body
still matches the seal.

It would not prove:

- That the report is correct, that the target was measured honestly, or that the
  evidence bundle is the one claimed. The seal binds a report to its own
  contents and dataset hash. The signature binds a signer to the seal.
- When the report was produced, for Backend A. SSHSIG has no timestamp. Backend B
  has a transparency-log time.
- That the key was not stolen, or has not been revoked. Revocation is the
  verifier's allowed-signers file and nothing in Plumbline.

## Consequences

- Needs `ssh-keygen` (OpenSSH 8.0 or later for `-Y`) on both sides for Backend A.
  A host without it must exit with the configuration-error code, never report the
  signature as skipped or valid. Some minimal containers lack it: the sandbox this
  proposal was drafted in does not have it.
- Subprocess calls handle key material and untrusted signature text, so they must
  pass arguments as a list, never through a shell, and write temporary files with
  restrictive permissions. The key path is printed, the key is not.
- The signature schema gains new `algorithm` values. Older Plumbline versions
  that read such a file already refuse an unknown algorithm; the proposal relies
  on that existing behavior and would test it.
- Key custody becomes the signer's problem, as with any asymmetric scheme, and
  the docs would say so as plainly as ADR 0002 does for the shared secret.

## Alternatives considered

- **Hand-written Ed25519 in the standard library.** Rejected again for the reasons
  in 0002: constant-time arithmetic is not something to improvise.
- **An optional extra that imports `cryptography` or PyNaCl.** Workable, and the
  simplest to implement. Rejected as the default because it puts the first
  third-party package inside the process that parses untrusted reports, and
  changes the SBOM claim from zero to non-zero runtime dependencies for the users
  who opt in. Remains the fallback if `ssh-keygen` availability proves a problem.
- **GPG signatures.** Mature, but a larger surface and a harder trust model than
  SSHSIG for the same job.
- **Sign in a separate tool and document it.** The seal digest is already
  printed, so anyone can sign it with a tool of their choice today. Rejected
  as the only answer because without a defined message, namespace and file
  format, two parties cannot interoperate and `verify` cannot check anything.
- **Do nothing.** Remains the correct choice if no consumer needs a verifier who
  shares no secret with the signer. 0002 said to wait for a real need.

## Tests this would require

Following the repository's rule that a check which has only passed has not been
shown to work:

- A signature made with an untrusted key is refused.
- A valid signature over an edited report is refused by the seal check first.
- A signature in the wrong namespace is refused.
- An HMAC signature offered where `--require-algorithm` names an asymmetric one
  is refused.
- A host with no `ssh-keygen` produces the configuration-error exit code.
- The existing HMAC tests in `tests/test_signing.py` pass unchanged.

## Open questions

1. Is there a concrete consumer who needs this, or should the status stay
   Proposed until one exists?
2. Backend A only, or both?
3. Should `plumbline verify` print the principal that verified, as it prints the
   key id for HMAC today?

## References

- [ADR 0002](0002-shared-secret-report-signatures.md)
- `src/plumbline/signing.py`
- `.github/verify-release-tag.sh` and `.github/allowed_signers`
- `docs/feature-expansion-ideas.md`, idea 1
