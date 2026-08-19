# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This is a pre-1.0 project: while the version stays below `1.0.0`, a MINOR bump
may break the interface.

## [Unreleased]

### Fixed

- **A suite that stopped running was reported as nothing having changed.**
  Switching a suite off in a target's configuration is the one edit that
  removes a check outright, and it was the one edit the baseline comparison's
  summary line reported as clean: `baseline: no verdict changed and no score
  moved`, exit 0. A suite that did not run has no score to move and no verdict
  to flip, so it appeared in none of the comparison's other terminal lines
  either — the `removed_suites` list was computed, put in the JSON and printed
  in the markdown report, and dropped from the one line a build log shows.
  Reproduced against the bundled demo by disabling `privacy` and
  `representational_harms`, both floor 1.00 and both in the committed baseline:
  the gate printed the clean-bill sentence and returned 0. The summary now
  leads with the suites the two runs do not share and names them, the terminal
  lines carry a `NOT RUN:` row per dropped suite ahead of the flips and moves,
  and the clean-bill sentence is emitted only when the suite sets match.
  Verdicts and exit codes are unchanged: a dropped suite is still not a
  failure, it is now visible. See decision 34 in `DESIGN.md` for what is left
  open.
- **Four more fail-open defects, each one a `PASS` a check had not earned.**
  Reproduced on `v0.1.0` first, then fixed, then pinned by a test in
  `tests/test_fail_closed.py`. Two of them are holes in the fix released in
  0.1.0, which is why they are listed the same way.
  - **Silence that gets past `.strip()`.** 0.1.0 stopped a target returning 174
    *empty* responses from scoring a perfect `1.0000` on five suites. A target
    answering every item with `"."` — or `"..."`, an emoji, a zero-width space,
    or a bare `[src-id]` — scored the identical `1.0000` on the identical five
    suites, with the gate returning PASS and exit 0. A response now counts only
    if something in it survives normalization, one predicate (`suites.readable`)
    that every suite reads, `smoke` included. The `unverifiable` block
    distinguishes `silent` from `unreadable`.
  - **A readable response that asserts nothing.** `"the and of to"` has content
    tokens removed by the stopword list, so the support measures answered 1.0
    and `groundedness` and `citation_accuracy` scored it a perfect pass. Such
    items are `no_claim`: excluded, named, never scored. A response that is only
    citation markers scores zero in `citation_validity` and `citation_accuracy`
    rather than 1.0 for pointing at a passage it took nothing from.
  - **Silence nobody counted.** Excluding an unreadable item instead of scoring
    it 1.0 opened the quieter version of the same hole: a target that answered a
    third of the demo corpus and returned nothing for the other 116 items passed
    a gate enabling `groundedness`, `privacy`, `representational_harms`,
    `fairness` and `cross_language` — exit 0, five green rows, each annotated
    *116 unverifiable*. The runner now asks the finished run whether **any**
    enabled suite scored those items zero, and refuses with the
    configuration-error code when none did, naming the items and the suites that
    would have counted them. **This can turn a previously green run into exit
    4** for a consumer whose evidence contains empty responses and whose suite
    selection excludes `smoke`, `refusal` and `multilingual`; enabling one of
    them turns it into the measured FAIL it always was.
  - **A run id could be borrowed.** The report seal is a plain sha256, so an
    editor can recompute it — the seal proves the copy in front of you is the
    copy that was written, and nothing more. A report could therefore be edited
    (a target name, a floor, a dataset hash), re-sealed, and still present the
    run id of an earlier trusted run: the id that names its output directory and
    that `plumbline baseline` copies into the committed bar as `source_run_id`.
    `plumbline verify` and `plumbline baseline` now recompute the run id from the
    inputs the report itself carries and refuse a report whose contents do not
    generate its id. The derivation is part of the file format from here on.
  - **The reproducibility step in this repository's own CI could not fail on a
    moved run id.** `git diff --exit-code -- audits baselines` cannot see a new,
    untracked run directory, so anything that moved the run id left the
    committed report in place and the step green. It checks `git status
    --porcelain` as well now.
  - **`gate/plumbline-gate.sh` asked CI not to bypass the pin.** "CI must never
    set `PLUMBLINE_SRC`" was a sentence in a comment. The runner now refuses the
    bypass when `CI` is set, which is every major provider.

### Added

- **`forbidden_claims` on an item: strings the response must not *assert*.**
  `forbidden` still means "must not appear", checked by substring, and remains
  the default. The new list excuses an occurrence when an explicit denial marker
  sits between the start of its clause and the occurrence, so a system that
  correctly answers "No, the deadline is not the 15th" stops failing a screen
  for "the deadline is the 15th". Read by `representational_harms`, `privacy`
  and `adversarial`, tagged with the same coupling cause. The markers are a word
  list, so they are covered by the judge configuration hash; the model judge
  delegates the check to the lexical one on purpose. From a downstream
  consumer, where mapping "must not be asserted" onto "must not appear" failed
  four items for correctly denying a claim.
- `plumbline verify` states its own boundary: tamper evidence, not
  authentication.
- An empty string in `forbidden` or `forbidden_claims` is a bundle error. A
  screen for nothing is not a screen.
- **A published evidence page**, `site/index.html`, generated by
  `tools/build_site.py` from the committed report and proof — and by *running*
  the three refusals it renders, in a temporary copy of this repository's own
  evidence, aborting the build if any of them returns a different exit code or
  if the documented command stops reproducing the committed run id. The
  committed page must be exactly what today's evidence produces:
  `tools/build_site.py --check` enforces that on every test run and before
  every deploy, and `tests/test_site.py` proves the check can fail.
  `.github/workflows/pages.yml` deploys it; enabling Pages is a repository
  setting and is deliberately not done here.

### Changed

- The judge configuration hash moves (the denial markers are part of it), so
  the committed demo audit, its baseline and `proof/matrix.*` are regenerated,
  and a comparison against a 0.1.0 baseline is refused as incomparable — which
  is the harness declining to subtract scores produced by different rules, and
  is correct of it.

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
