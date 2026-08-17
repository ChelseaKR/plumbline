# Security Policy

## What this project is, for scoping purposes

Plumbline is an offline command-line harness. It has **no runtime
dependencies** outside the Python standard library, no server, no accounts, no
credentials, and no persistent store. It reads files you point it at and writes
report files. Two paths reach the network, both off by default and both
explicit: recording against a live target over HTTP, and the optional model
judge. Neither is used by the bundled demo, the test suite, or CI.

## Supported versions

Pre-1.0. Only the latest `0.y` line receives fixes; there is no LTS branch.
Once a `v1.0.0` is tagged this section will name a supported major-version
window.

## Reporting a vulnerability

Report privately through
[GitHub's private vulnerability reporting](https://github.com/ChelseaKR/plumbline/security/advisories/new)
(the repository's "Security" tab, then "Report a vulnerability") rather than in
a public issue. If that is unavailable, email the maintainer named in
`CITATION.cff`.

| Stage | Target |
|---|---|
| Acknowledgement | within 7 days of receipt |
| Assessment shared with you | with the acknowledgement or shortly after |
| Fix or documented mitigation | within 90 days of confirmation, sooner for severity |
| Coordinated disclosure | by mutual agreement |
| Credit | named in the advisory and the CHANGELOG, unless you prefer otherwise |

## In scope

- A path that lets crafted input in `datasets/`, a config file, or a recorded
  response escape the harness: file writes outside `--out`, code execution,
  or path traversal.
- A defect that lets a tampered dataset or an edited report pass `plumbline
  verify` or reach a verdict. Integrity refusal is the property this project
  exists to hold, so a break there is a security bug and not only a correctness
  bug.
- The subprocess adapter executing something other than the configured program.
- A network call from a path documented as offline.

## Out of scope

- Scores produced from the bundled synthetic dataset. It demonstrates the
  instrument and measures nothing about any real system; a number from it
  being "wrong" is not a vulnerability.
- The report seal being forgeable by someone who can rewrite the report. This
  is stated in the README: the seal is **tamper evidence, not
  authentication**. It carries no secret and vouches for nobody.
- Anything requiring the attacker to already be able to run code as you.

## Known issues

Fixed fail-open defects are recorded in `CHANGELOG.md` and pinned by tests in
`tests/test_fail_closed.py`, each reproduced on the released version before it
was fixed.
