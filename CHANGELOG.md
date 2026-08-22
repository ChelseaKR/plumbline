# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This is a pre-1.0 project: while the version stays below `1.0.0`, a MINOR bump
may break the interface.

## [Unreleased]

### Added

- **A local gate.** `make verify` runs the linter, the full suite under a
  branch-coverage floor, and the check that the published evidence page is what
  the committed evidence produces. A new `quality` job in `tests.yml` runs the
  same target in CI, so all three block rather than only being available. The
  existing version matrix is untouched and still proves what it proved before:
  that the suite passes on a bare interpreter with nothing installed.
- **Ruff, pinned at `>=0.15.0` and green.** Ruff's default rule set, which
  caught four unused test imports, now removed. F541 is ignored and the reason
  is in `pyproject.toml`: `audit.py` digests `src/plumbline/` into
  `harness_source_sha256`, so touching any source file invalidates the
  committed audit, the baseline, `proof/matrix.md` and the published page, and
  that is not a price worth paying to delete seven redundant `f` prefixes. The
  wider portfolio rule set is *not* enabled: measured on 2026-08-17 it has 304
  findings, 232 of them line length. Configuring it and excluding the findings
  would be the badge this repository exists to argue against, so the count is
  recorded as a gap in the README's conformance table instead.
- **A branch-coverage floor of 90%**, enforced by `make verify`. Measured at
  94% over `src/` on 2026-08-17. Coverage wraps the same `unittest discover`
  run; it does not change what executes.
- **`SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`, `CITATION.cff`,
  `.python-version`, `uv.lock`, `.pre-commit-config.yaml`, and an ADR log**
  seeded at `docs/adr/0000-record-architecture-decisions.md`. The runtime is
  unchanged and still depends on nothing outside the standard library; ruff and
  coverage live in a `dev` dependency group that `plumbline` never imports.
- **`security.yml`**: Semgrep SAST and a full-history TruffleHog secret scan,
  both on push and pull request rather than on a schedule or a button, plus
  gitleaks diff-scoped in pre-commit and a Dependabot configuration watching
  the action pins. Every `uses:` in the repository is pinned to a
  40-character SHA; Dependabot is what keeps those pins from going stale
  quietly.
- **A Standards Conformance table in the README**, declaring all fifteen
  standards with a state for each. Where a standard is not met the shortfall is
  named and counted rather than described as planned. Three are recorded as
  real gaps with measurements: mypy is not wired at all (27 errors by default,
  172 under `--strict`), 14 functions exceed a McCabe complexity of 10, and the
  Python floor is 3.11 against a portfolio floor of 3.12.
- **A fifteenth suite: `conversational_integrity`.** Every other suite reads
  `response_for(item.id)` — the final turn only — so a target that leaks a
  forbidden phrase, or drops a refusal, midway through a conversation and then
  produces a clean final answer was invisible to all of them: the
  wrong-paragraph problem `passage_attribution` exists for, for turns instead
  of paragraphs. `Item.turns` and a response record's `turn_responses` are
  additive (`docs/adr/0003-multi-turn-items-are-additive-not-a-new-bundle-format.md`):
  an empty `turns` list is byte-identical to every item this
  harness has ever loaded, and `FORMAT_VERSION` does not move. Opt-in twice
  over, the same way `passage_attribution` is — an item declares `turns` and
  was additionally *recorded* per turn, or it is UNVERIFIABLE, never a pass.
  The demo bundle grows from 174 to 178 items: four hand-written multi-turn
  escalation probes, all clean, and a 21st defect-injection case plants a
  mid-conversation leak with a clean final turn to prove the suite catches it
  while every other suite — `adversarial` included — stays indifferent.
- **`plumbline sign` / `plumbline verify --key-file`.** A detached
  HMAC-SHA256 signature over a report's own seal, closing the gap `verify`
  already named: the seal is tamper evidence, not authentication.
  Deliberately shared-secret rather than public-key —
  `docs/adr/0002-shared-secret-report-signatures.md` records why a from-scratch asymmetric
  implementation or a first runtime dependency were both worse choices than
  saying plainly what HMAC does and does not prove.
- **`--sarif` on `audit` and `gate`.** Projects failing and UNVERIFIABLE
  per-item records onto SARIF 2.1.0, so a consuming repository's CI can
  upload real findings for inline PR annotations instead of only a pass/fail
  exit code — no new measurement, the same report data rendered a second way.
- **`plumbline history append` / `history check`.** An append-only run
  history and a longitudinal trend view on top of the pairwise baseline
  comparison, which by design cannot see a regression smaller than one
  comparison's MDE accumulate across many runs. Reports one plain fact —
  a suite's score non-increasing across every step of the trailing N
  comparable runs, with at least one real decrease — no new interval, no
  p-value; `docs/adr/0001-longitudinal-history-is-observation-not-inference.md`
  records why a real trend statistic was left out of scope.
  Off by default in CI; `--fail-on-decline` opts in.
- **`plumbline retire`.** A recording-retention and redaction lifecycle
  companion to `plumbline record`, closing the Data Governance gap the
  README already named: no data card, no stated retention position for
  recordings. Reuses `privacy.py`'s own PII screen against every recorded
  response; past a configured age, a bundle still carrying a flagged pattern
  is refused unless `--redact` rewrites it in place and reseals.
  `docs/recordings-data-card.md` is the data card half of the same gap.
- **`sbom.cdx.json`, `tools/build_sbom.py`, `.github/workflows/release.yml`.**
  A CycloneDX SBOM generated from `pyproject.toml`, checked for staleness the
  same way the published evidence page is; a release workflow that verifies
  the SBOM, runs OpenSSF Scorecard, and keyless-signs the SBOM with Sigstore
  cosign over GitHub's own OIDC token. The workflow has not been exercised
  against a real tag — it says so at the top of the file, the same "not yet
  met, not asserted as done" posture the Standards Conformance table already
  takes on the two gaps this closes.

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
