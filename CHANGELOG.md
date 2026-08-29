# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This is a pre-1.0 project: while the version stays below `1.0.0`, a MINOR bump
may break the interface.

### Fixed

- **The published page had no canonical URL, on an origin it shares with five
  other sites.** `site/index.html` carried a title and a description and
  nothing else: no `<link rel="canonical">`, no Open Graph, no Twitter card, so
  a link to it previewed as a bare URL. That is not only cosmetic here. The
  page is served under a project *path* on `chelseakr.github.io`, so the
  canonical a single-domain habit produces (`/`) is not this site's root but a
  different address that 404s, and all six sites sharing the origin would claim
  it. `tools/build_site.py` now renders a canonical, `og:*` and `twitter:card`
  from one `PAGE_TITLE` and one `PAGE_DESCRIPTION`, so `<title>`/`og:title` and
  `description`/`og:description` cannot drift apart. There is no `og:image`:
  this repository ships no image and `test_it_is_self_contained` exists to keep
  it that way, so the card is `summary`, which promises none.
  The description also stopped carrying a literal newline: it wrapped across
  two source lines inside the `content` attribute, which is legal HTML and
  reads fine, and is still a stray control character in the one string a search
  result quotes verbatim.
  `test_the_head_names_this_page_and_not_the_shared_origin` extends the
  existing published-page checks rather than starting a parallel suite, and
  asserts the project path is *present* rather than that a canonical merely
  exists, because an origin-rooted canonical passes the weaker check and is the
  bug. Observed failing four ways: canonical line deleted; `PAGE_URL` set to
  the bare origin; a newline reintroduced into the description;
  `twitter:card` raised to `summary_large_image` with no image to show.

- **The published page's contrast check could not see a colour nobody had
  listed.** `tools/check_site_a11y.py` proves that nine hand-written
  `CONTRAST_PAIRS` meet WCAG AA in both palettes. It said nothing about a
  colour added to `:root` later and never added to that list: the page would
  grow a colour, the check would go on reporting "all 9 declared pairs meet
  WCAG AA", and nothing would say the ninth was not the last one.

  That is the same shape this repository refuses one level down. `plumbline
  validate` treats a file *present but not listed* in `checksums.json` as an
  integrity refusal rather than a pass, and the accessibility suite refuses a
  target that declares no contrast pairs at all ("unverified contrast is not
  passing contrast"). The page holding targets to that standard was not held
  to it itself, which is the objection its own module docstring raises: "the
  thing a harness holds targets to and never checks about itself is a standard
  that only ever points outward."

  An eighth check, `palette_coverage`, closes it. Every colour the page
  declares is either in a checked pair or in `UNCHECKED_PALETTE_VARS` with a
  written reason; a colour that is neither fails the gate. It also refuses a
  stale exemption for a colour the page no longer declares, and palettes whose
  light and dark halves declare different colours, which would leave one theme
  silently inheriting the other's value.

  Today exactly one colour is exempt: `--rule`, a 1px border never used for
  text, whose bar is WCAG 1.4.11's 3:1 for non-text rather than the 4.5:1 this
  check measures. It was already outside the list; the difference is that the
  omission is now a decision on the record instead of a gap.

  Demonstrated on the real page, not only a fixture: adding `--warn:#ffcc00`
  to both palettes leaves `contrast` reporting its nine pairs clean and makes
  `palette_coverage` fail, exit 1.

- **`make verify` passed on trees `.github/workflows/tests.yml` rejects.**
  Three of that workflow's steps were inline script with no target behind
  them: the byte-for-byte reproduction of the committed audit, the re-check of
  the committed report against its own seal, and the tamper drill. The
  Makefile said so deliberately, with a reason -- both mutate the working
  tree, and "a gate people learn to run `git checkout --` after is a gate
  people learn to ignore."

  The reason was right about the symptom and wrong about the cure. Neither
  check needs to mutate anything. `make reproduce` writes the run into a
  temporary directory and compares with `diff -r`; `make tamper-drill` tampers
  with a copy of the checkout. Both are in `make verify` now, and the checkout
  is untouched by either.

  `diff -r` and not a content diff of tracked files: it fails on a changed
  byte, on a report the run no longer writes, *and* on a directory the run
  writes that is not committed. The run id is the output directory's name, so
  a change that moves it leaves the committed directory untouched and writes a
  new one beside it -- the failure the workflow's own comment already named.

  Both targets carry a floor against passing over nothing: `reproduce` refuses
  an empty `audits/`, and `tamper-drill` refuses a copy with no dataset in it.
  The drill still captures exit codes explicitly rather than leaning on `&&`,
  and it was demonstrated catching a tamper that never landed: pointing its
  edit at a string absent from the file makes the gate exit 0 instead of 3,
  and the drill fails with "expected exit 3 (integrity refusal), got 0".

  `tests/test_ci_parity.py` keeps it closed: every `run:` step in tests.yml
  must be a make target, that target must exist, and `verify` must reach it.
  Demonstrated failing twice -- by reintroducing an inline CI-only step, and
  by dropping `reproduce` from `verify`.

  The matrix job keeps the property it exists for. Its steps run `make
  test-bare`, `make reproduce` and `make tamper-drill`, all of which use plain
  `python3`: `make` is not a Python package, so routing the suite through a
  target does not spend the claim that Plumbline runs on the standard library
  alone with nothing installed.

  `.github/workflows/security.yml` is deliberately **not** held to this rule,
  and the exemption is a tooling fact rather than a preference: its semgrep
  step runs inside a pinned semgrep container and its secret scan is a pinned
  marketplace action, so neither is a shell command a Makefile could run
  identically. `make sast` is added as a local approximation of the first and
  says so in its comment.

- **`.semgrepignore`'s own comment described the opposite mechanism.** It said
  "Semgrep's own defaults (.git, node_modules, etc.) still apply; this file only
  adds exclusions". A repository-root `.semgrepignore` *replaces* the built-in
  list rather than extending it, and the built-in list drops `tests/`. Measured
  both ways on 2026-08-28 with `semgrep scan --config p/python .`: with the file
  present, 77 of 77 tracked Python files are scanned and 1 is skipped; with it
  moved aside, 46 are scanned and 32 are skipped, all 31 files in `tests/` among
  them. The coverage is right and the reason recorded for it was not, which
  means it was holding by accident: this repository's tests are scanned only
  because the file exists at all, for an unrelated single HTML fixture. The
  comment now carries the measurement and a warning that adding a broad path
  there takes the coverage back silently.

### Added

- **Every report now says which suites did *not* run.** A report has always
  listed the suites that ran; nothing listed the suites that did not, so a
  `PASS` from a configuration that never enabled `privacy` was
  indistinguishable, on its face, from a `PASS` that checked everything.
  [`docs/responsible-tech.md`](docs/responsible-tech.md) names this twice —
  as a residual risk ("nothing about the word `PASS` on its own discloses
  that") and as a misuse the repository "can name but not prevent" — and
  names re-reading the suite list as the only defense. That control asks a
  reader to notice an *absence* in a fifteen-row table, which requires
  knowing the registry by heart, and asks it of the reader least likely to
  be holding the table.

  So `src/plumbline/scope.py` computes a `scope` block for every run:
  every implemented suite that was not scored, and which of two reasons
  applies — `absent` (the configuration never mentions it) or `disabled`
  (it names the suite and sets `enabled = false`). Both are stated because
  they read differently in a review. It renders as a `## Scope` section in
  the Markdown report and as one line on the terminal, from `audit` and
  `gate` alike:

  ```
  GATE: PASS — target riverbend-demo, dataset 949197da4dd6, run 3d30a46c4f24b12b
  all 12 suites passed:
  scope: 12 of 15 implemented suites scored; NOT scored: adversarial
         (absent), privacy (absent), refusal (disabled)
  ```

  It never changes a verdict, and refusing a partial configuration was
  considered and rejected: phasing coverage in is legitimate, and the
  harness cannot tell that case from an evasive one. Three properties are
  deliberate — the section renders even when nothing is missing, so its
  absence cannot be read as full coverage; the denominator comes from the
  suite registry rather than a literal, so a suite added later is counted
  without anyone remembering to; and it lives inside the sealed report
  body, so it cannot be edited off a report without `plumbline verify`
  refusing it. See
  [ADR 0004](docs/adr/0004-unscored-suites-are-disclosed-not-enforced.md)
  for the alternatives weighed, including failing the gate, a
  `--require-all-suites` flag, and a defect-injection case.

### Changed

- **A misspelled key inside `[suites.<id>]` is now a configuration error,
  and `enabled` must be a real boolean.** Both were silent, and both
  produced a gate weaker than the reviewable file that configures it says
  it is. Observed on the previous code, with one configuration:

  ```
  [suites.accuracy]
  enabled = true
  flooor = 0.99      # a typo
  [suites.privacy]
  enabled = 0        # not a boolean
  [suites.smoke]
  enabled = true
  floor = 1.0
  ```

  ```
  load_config ACCEPTED it
    suites actually gated: {"accuracy": 0.75, "smoke": 1.0}
    the file says accuracy floor 0.99; the gate runs it at 0.75
    the file says privacy enabled = 0; privacy is NOT gated, silently
  ```

  TOML ignores a key nothing reads, so the suite fell back to the
  harness's *demonstration* default — a number the target's own
  configuration does not state anywhere. `enabled = 0` switched a suite off
  without a word; `enabled = "false"` is a non-empty string, so it read as
  "off" to a person and left the suite on. Both are refused now, each with
  a message saying what the silent behaviour was. This will reject
  configurations that load today; that is the point, since those
  configurations are not running the gate they appear to describe. Six
  tests in `tests/test_fail_closed.py`, all observed failing on the
  previous code.

## [Unreleased]

### Fixed

- **The GitHub action's outputs could describe a different run than the
  one that had just executed.** `action.yml` found the report by taking
  the last directory in `--out` by name: `find "$INPUT_OUT" -type d |
  sort | tail -n1`. A run id is a truncated sha256 of the run's inputs
  (`audit.compute_run_id`), not a timestamp, and `report.write_reports`
  never removes an earlier run from the output directory — so the two
  assumptions holding that line up are both false as soon as a second
  run lands in the same `--out`. Observed with three runs into one
  directory: the action named the run that sorted highest, and with a
  stale passing run left beside a failing one it published
  `verdict=PASS` for a run whose real verdict was `FAIL`, with
  `report-json`, `report-md` and `sarif-json` all pointing at the wrong
  report. The paths are now read back from what the run itself printed
  (`reports:` and `sarif:` on the gate's own stdout, teed so the build
  log is unchanged, with `${PIPESTATUS[0]}` preserving the gate's exit
  code). Exit 0 and exit 1 mean a report was written, so if no verdict
  can be read back from one the step now fails with the internal-error
  code instead of exiting 0 having published nothing. A verdict that is
  not `PASS` or `FAIL` is refused rather than passed through to a
  workflow that branches on it. The step is now executed by the test
  suite rather than grepped: six tests run the real shell out of
  `action.yml` against a stubbed gate, and all six fail on the previous
  version.

- **An unlabelled `<button>` was invisible to the `accessibility` suite.**
  `CONTROL_TAGS` held `{"input", "select", "textarea"}`, so `<button>`
  never reached `snapshot.controls` and never reached the
  `control_labels` check. An interface whose only send control was an
  icon-only `<button id="send"></button>` scored `control_labels` 1.00
  and the whole suite 1.00 against its floor of 1.00 — a green row for
  the one WCAG 4.1.2 defect a chat interface is most likely to have.
  `<button>` is now a control, and its accessible name is read the way
  a browser's accessible name computation reads it, which closes two
  adjacent ways of passing that adding the tag alone leaves open: a
  `<button>` with no end tag collected every word after it and reported
  itself named on the rest of the page, and text inside an
  `aria-hidden="true"` subtree — announced to nobody — counted as a
  name. An `<img alt>` inside a button does count, because it is a name
  a screen reader reads, and a check that fails correct markup is a
  check people switch off. A whitespace-only `aria-label`, `title` or
  `aria-labelledby` is no longer a name either, for any control. The
  failure now says which of these it was rather than only that the
  control is unnamed. Eleven tests pin it, each observed failing on the
  previous code. No demo score moved: the demonstration interface
  snapshot has no `<button>` in it, which is how this survived. The
  committed audit, baseline, proof matrix and site are regenerated for
  the source hash.

- **`$125.00` and `$125` were different numbers to the judge.**
  `judges.extract_numbers` stripped commas and a trailing dot and
  stopped there, so a response that correctly said "$125" against a
  source that said "$125.00" failed the number-support check in
  `groundedness` as an unsupported number, and two languages stating the
  same fee with different formatting were a `cross_language` hard
  failure. Found while building the first question set from a real
  service's published guidance, which writes fees both ways on one site.
  Trailing zeros after a decimal point are now dropped (`10.50` becomes
  `10.5`, `1,000.00` becomes `1000`); a token with more than one dot is
  left as found, since a version string is not a decimal. This is a
  scoring-rule change, so the lexical judge's config version moves 3 to
  4 and the judge configuration hash moves with it: a comparison against
  a baseline produced before this is refused as incomparable, which is
  the harness declining to subtract scores produced under different
  rules. The committed demo audit, baseline, proof matrix and site are
  regenerated; no demo score moved. Three tests pin it, each shown
  failing on the previous code.

### Changed

- **OpenSSF Scorecard moved out of `release.yml` into its own `scorecard.yml`.**
  The action refuses to analyze anything but the repository's default
  branch, and `release.yml` only ever triggers on a `v*` tag — a combination
  that can never pass, discovered by the `v0.2.0` retag (see `[0.2.0]`'s own
  Fixed entry). `scorecard.yml` follows the pattern in OpenSSF's own
  [`scorecard-analysis.yml`](https://github.com/ossf/scorecard/blob/main/.github/workflows/scorecard-analysis.yml):
  push to `main`, plus a weekly schedule. First run, 2026-08-23: **6.1/10**
  — 10/10 on Security-Policy, Dangerous-Workflow, Binary-Artifacts,
  Token-Permissions, Dependency-Update-Tool, License, and Vulnerabilities;
  8/10 on Pinned-Dependencies and Signed-Releases; 0/10 on Branch-Protection,
  Code-Review, SAST, Maintained (the repository is under 90 days old), and
  CII-Best-Practices. The SAST score is a real gap in what Scorecard
  *credits*, not in what runs: Semgrep and TruffleHog already run on every
  push and pull request (see the Security & Supply-Chain conformance row);
  Scorecard's check does not recognize that configuration.

### Fixed

- **6 Semgrep findings that only surfaced on push to `main`, not on PR
  checks.** `semgrep ci` diffs against the PR base on a `pull_request`
  event — only new findings block — but scans the whole tree on a plain
  push, with nothing to diff against. 3 pre-existing finding types
  (6 occurrences) had been invisible in every PR check this session ran
  and were only found while auditing which jobs are safe to require for
  branch protection: a real `run-shell-injection` primitive in
  `publish-pypi.yml` (`${{ github.event.inputs.confirm }}` interpolated
  directly into a `run:` script rather than passed through `env:`),
  four floating `@v4`/`@v5` action tags in `gate/github-actions.example.yml`
  now pinned to 40-character SHAs, and one real false positive —
  `python.django-no-csrf-token` firing on a static HTML fixture's
  `<form method="post">` with no Django anywhere in the stack — fixed
  with a documented `.semgrepignore` entry rather than editing the
  fixture, which is content-hashed into `checksums.json`. Verified with
  `semgrep scan --config auto` locally: 0 findings, 0 blocking.

## [0.2.0] - 2026-08-22

Six proposals from `docs/feature-expansion-ideas.md`, merged as six
separate pull requests (#8-#13): a fifteenth suite, detached report
signatures, SARIF export, run history, recording retention, and a
checked-for-staleness SBOM with an as-yet-unexercised release workflow.
Minor, not patch: new CLI surface (`sign`, `history`, `retire`) and a
new suite are additions, not fixes, and this project's own SemVer
statement treats those as MINOR while below `1.0.0`.

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

### Added

- **A Definition of Done and a metrics ledger**
  ([`docs/definition-of-done.md`](docs/definition-of-done.md),
  [`docs/metrics-ledger.md`](docs/metrics-ledger.md)), closing the gap
  the Quality & Metrics conformance row named against itself. The
  Definition of Done is a mechanical, checkable list — a command or a
  factual question, never "looks good" — of what has to be true before a
  change here is finished, split into what every change owes, what a
  `src/plumbline/` change owes on top of that, and what a change to this
  repository's own claims about itself owes. The metrics ledger is this
  repository's code-quality numbers (suite count, test count, coverage,
  ruff, mypy, complexity) as an append-only history rather than a single
  point-in-time table row; every row was produced by checking out that
  tagged or merged commit in an isolated worktree and running the same
  commands `make verify` runs today, not recalled or carried forward —
  which caught two numbers this session would otherwise have gotten
  wrong (mypy's default-mode error count immediately before it was
  wired was 29, not the 27 an earlier document's stale figure implied).
  Both name against themselves that nothing currently enforces they stay
  current.
- **An operations runbook** ([`docs/operations-runbook.md`](docs/operations-runbook.md)),
  closing the gap the Observability conformance row named against itself.
  Split for the two people who actually hit it: someone gating a
  repository with Plumbline (every exit code, keyed to what it means and
  what to do, plus the gate hanging instead of exiting), and someone
  maintaining this repository (CI failure modes, the security and release
  workflows, and the human-only duties nothing here schedules — a
  retention sweep, a signing-key rotation, a tag push). Documents, for
  the first time in one place, the exact two-pass baseline regeneration
  order this repository's own artifacts require after any
  `src/plumbline/` edit — self-referential because the baseline's own
  hash feeds into the run id of the next report that names it, and the
  single most common way this repository's own CI has actually gone red.
- **`tools/check_site_a11y.py`** holds the published evidence page,
  `site/index.html`, to the same kind of structural check
  `src/plumbline/suites/accessibility.py` runs against a *target's*
  captured interface — closing the gap the Accessibility conformance row
  named against itself. Seven checks: language declaration, heading order,
  link text, image alt text, a single `main` landmark, zoom not disabled,
  and WCAG AA contrast — computed with the same `contrast_ratio` function
  the scoring suite uses, against both the light and dark palette declared
  in the page's own `<style>` block, since `color-scheme: light dark`
  means a visitor gets whichever one their system prefers. Wired into
  `make verify` (folded into `site-check`) and into
  `.github/workflows/pages.yml`, which now refuses to deploy a page that
  fails its own accessibility standard. Pinned by
  [`tests/test_site_a11y.py`](tests/test_site_a11y.py), 27 tests proving
  each of the seven checks can actually fail, not only that the committed
  page currently passes.
- **`mypy` is wired into `make lint` and CI**, checking `src/plumbline` at
  mypy's default (non-strict) setting; both `make lint` and CI's `quality`
  job now fail on a type error, not only on a ruff finding. The gap this
  closes was recorded against itself in the README's Code Quality
  conformance row: 27 default-mode errors, mostly a `Judge` protocol that
  named only the methods each suite happened to call rather than the full
  contract every judge implements, plus a handful of guard clauses (a
  `None`-checked value, an already-validated dict) that a static checker
  cannot see across the method boundary they live on the other side of.
  Fixed rather than suppressed in every case; `pyproject.toml`'s
  `[tool.mypy]` records why this stops short of `--strict` (174 findings,
  almost all a bare `dict` missing its type argument) as the next open gap,
  the same way the ruff select set records its own.
- **A longer-form "what it caught in its own harness" draft**
  ([`docs/what-it-caught-in-its-own-harness.md`](docs/what-it-caught-in-its-own-harness.md)),
  written for external publication (a blog post or similar), distinct from
  the README section it is drawn from. Walks through the silence/absence
  defect across its three rounds, the consumer-found wrong-paragraph gap,
  and the coupling-disclosure fix, as narrative rather than changelog
  entries. Marked as a draft in its own header — edit before publishing.
- **A dated responsible-tech statement** ([`docs/responsible-tech.md`](docs/responsible-tech.md)),
  closing the gap the Responsible-Tech Framework conformance row named
  against itself. Written from the point of view of the people a graded
  system serves rather than the people running the harness: what a `PASS`
  does and does not mean, residual risks present even when every suite
  works exactly as designed (a floor is a policy choice, not a ceiling on
  harm; a lexical screen catches what is on its list; the demo dataset's
  coverage is not the world's), misuse this repository can name but not
  prevent, and — in its own closing section — that the statement itself has
  not been reviewed by anyone outside this repository.
- **A model card for the optional model judge**
  ([`docs/model-card-judge.md`](docs/model-card-judge.md)), closing the gap
  the AI Evaluation conformance row named against itself. Covers what the
  judge decides (only `answer_score`) and what stays lexical regardless,
  how a judgment is produced and cached, the adversarial surface a second
  model widens and its mitigation, and the limitations the card names
  against itself — chiefly that nothing measures how often the model judge
  agrees with a human rater.
- **PyPI packaging.** `pyproject.toml`'s distribution name is now
  `plumbline-eval` — `plumbline` is taken by an unrelated, long-dormant
  geospatial package; the import name, the package directory, and the
  `plumbline` CLI command are all unaffected. `sbom.cdx.json` and `uv.lock`
  regenerated to match. `.github/workflows/publish-pypi.yml` is a
  manual-only (`workflow_dispatch`, with a typed confirmation) publish
  workflow using PyPI's keyless Trusted Publishing — no stored secret.
  Verified locally: `python3 -m build` produces a clean sdist and wheel, and
  installing the wheel into a fresh virtualenv gives a `plumbline` command
  that runs identically. Not yet run: publishing needs a human to register
  the trusted publisher on PyPI first, which nothing in this repository can
  do on its own.
- **`action.yml`: pin the harness from GitHub Actions directly.** A second
  way to pin the gate for a repository whose CI is GitHub Actions, alongside
  `gate/plumbline-gate.sh` (which stays the way to gate from anything else).
  `uses: ChelseaKR/plumbline@<sha>` is the pin — the same mechanism this
  project's own workflows already use for `actions/checkout` — so a
  consumer needs neither the shell script nor a `plumbline.pin` file. Not
  yet exercised from an external consuming repository.

### Fixed

- **The `v0.2.0` tag itself, after it exposed two defects `release.yml`'s own
  header had flagged as possible.** The first push failed immediately:
  `actions/upload-artifact`'s pin was `ea165f8d65b6e75b540449e92b4886f43607fa9`,
  39 hex characters — one short of a real SHA-1 — so it could not resolve.
  Verified the correct SHA against the GitHub API
  (`ea165f8d65b6e75b540449e92b4886f43607fa02`) and swept every other `uses:`
  pin in every workflow file the same way; nothing else was wrong. The tag
  was deleted and re-pushed at the fixed commit, which is why this note is
  here rather than in a later version: the fix landed inside the commit
  `v0.2.0` actually points to. Retagging got further — a real, signed
  GitHub Release now exists for `v0.2.0` — but exposed a second, structural
  defect: OpenSSF Scorecard refuses to analyze anything but the default
  branch, and this workflow only triggers on a tag push. That one could not
  be fixed inside the same tag; see `scorecard.yml` under `[Unreleased]`.

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

[Unreleased]: https://github.com/ChelseaKR/plumbline/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ChelseaKR/plumbline/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ChelseaKR/plumbline/releases/tag/v0.1.0
