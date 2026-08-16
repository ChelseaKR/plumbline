# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This is a pre-1.0 project: while the version stays below `1.0.0`, a MINOR bump
may break the interface.

## [Unreleased]

## [0.1.0] - 2026-08-16

First tagged release. The harness was usable before this tag; what the tag
adds is a fixed point a consumer can name, and a statement of what changed
underneath them.

### Fixed

- **Nine fail-open defects, each of which could produce a `PASS` that had not
  been checked.** Every one was reproduced on `main` first, then fixed, then
  pinned by a test in `tests/test_fail_closed.py`. A verdict produced before
  this release can be a vacuous pass and should not be relied on.
  - A target returning **entirely blank responses scored a perfect `1.0000` on
    five suites** — `groundedness`, `privacy`, `representational_harms`,
    `fairness` and `cross_language` — and `plumbline gate` returned **PASS,
    exit 0** on those alone. Silence satisfied every check phrased as the
    absence of something bad. Suites now split: those asking whether the target
    behaved correctly score silence zero (`refusal`, `adversarial`), and those
    asking whether something bad is missing report it UNVERIFIABLE — excluded,
    named in the coverage line, never a pass.
  - Bundle integrity covered only the top level of a bundle: `hashed_files`
    used `iterdir`, so evidence in a subdirectory was sealed by nothing. The
    walk is recursive now, keyed by POSIX path relative to the bundle root, and
    it refuses symbolic links.
  - Files outside the sealed inventory were read: `bundle_dir / filename`
    resolved `../outside.jsonl` and `/etc/passwd` to a clean PASS. A declared
    file must now be relative, resolve inside the bundle, and be covered by a
    checksum.
  - Aggregation was `FAIL if any(v == FAIL) else PASS`, so `"SKIP"`, `None` or
    a typo landed on the pass branch. It is now `all(v == PASS)`, and results
    are validated first.
  - A crash exited 1, the code reserved for a measured failure. Crashes now
    exit 5. Every non-zero code still blocks.
  - `floor = 0.0` was accepted, and every score clears it. A check that cannot
    fail is now a configuration error.
  - A reference answer of `"   "` scored 1.0 against an empty response.
  - The run id did not include the target, so two systems audited against the
    same evidence, judge and floors collided and the second run silently
    overwrote the first.
  - `bundle_digest` joined `"<name>=<hex>\n"` lines, so a filename containing a
    newline could serialize as two files. Such names, and malformed digests in
    a hand-edited manifest, are refused at both ends. Existing bundle hashes
    are unaffected.
  - Nothing bound provenance to the report body, so a FAIL could be edited into
    a PASS with the run id, dataset hash and judge hash all still valid.
    Reports now carry `report_sha256` over their own canonical JSON;
    `plumbline verify` checks it, and `plumbline baseline` refuses to distil a
    report that fails it.

### Added

- Fourteen scoring suites: `smoke`, `accuracy`, `refusal`, `cross_language`,
  `multilingual`, `groundedness`, `citation_validity`, `citation_accuracy`,
  `passage_attribution`, `adversarial`, `fairness`,
  `representational_harms`, `privacy`, and `accessibility`.
- `passage_attribution`, the fourteenth suite, from a consumer's bug report: an
  answer can be grounded, cited, in the right language and not a refusal, and
  still be composed from the wrong paragraph of the right document.
- Per-suite confidence intervals and minimum detectable effect on every suite.
- Baseline regression comparison that refuses to compare incomparable runs.
- A pinned fail-closed CI gate for consuming repositories: `gate/plumbline-gate.sh`
  and a `plumbline.pin` file. The runner requires an exact 40-character commit
  hash and rejects a branch or a tag, because a moving ref means a green gate
  today can quietly mean something else tomorrow.
- Live-target recording over HTTP or against a local program, and an optional
  model judge — none of which the gate can reach.
- A defect-injection matrix (`proof/matrix.md`): for each suite, a planted
  defect that suite exists to catch, run through the real audit path. 20 of 20
  cases held, and every enabled suite has been observed failing.
- Provenance on every report: run id, harness version, `harness_source_sha256`
  over the installed package, seed, dataset hash, and judge configuration hash.

### Changed

- Continuous integration is enabled and green on CPython 3.11, 3.12, 3.13 and
  3.14. It was previously present but inert.

[Unreleased]: https://github.com/ChelseaKR/plumbline/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ChelseaKR/plumbline/releases/tag/v0.1.0
