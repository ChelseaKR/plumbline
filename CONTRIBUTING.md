# Contributing

## The gate

```sh
make verify
```

That is lint, the full test suite under a branch-coverage floor, and the check
that the committed evidence page is what the committed evidence produces. It
needs [`uv`](https://docs.astral.sh/uv/) and nothing else; no key, no network,
no third-party runtime package.

If you would rather not install `uv`, the suite alone still runs on a bare
interpreter, which is how CI runs it across CPython 3.11 through 3.14:

```sh
PYTHONPATH=src:tests python3 -m unittest discover -s tests
```

`make verify` deliberately leaves out two gates that CI runs: the byte-for-byte
reproduction of the committed demo audit, and the tamper drill. Both rewrite
files in the working tree. They belong in a disposable checkout, and
`.github/workflows/tests.yml` is where they live.

## The rule that governs changes here

**A step that cannot go red is a badge.** This project's argument is that a
check which passes because it did not run is worse than no check, so:

- A new gate ships with a test proving it can fail, not only one proving it
  passes on good input.
- A suite that has nothing to score is a configuration error, never a pass.
- A silent skip is a bug report. If you find one, say so in the pull request
  even if you are not fixing it.

## Changing the harness

Any change that moves a score, a hash, or a byte of a report will fail CI's
reproduction step until the committed audit under `audits/` is regenerated in
the same commit:

```sh
PYTHONPATH=src python3 -m plumbline gate --config examples/riverbend.toml --out audits
```

Regenerate it because the behaviour genuinely changed and you can say why in
the pull request. Regenerating it to make a red step go green is the failure
mode this repository is about.

## Style

- Ruff's default rule set is enforced by `make lint`. The wider portfolio rule
  set is not enabled yet and its outstanding findings are counted in the
  README's conformance table; do not add new findings under it.
- The runtime stays standard-library only. Development tooling goes in the
  `dev` dependency group and is never imported by `plumbline`.
- Tests are `unittest`, run by `unittest discover`. Coverage wraps that run; it
  does not replace it.

## Reporting a vulnerability

See [`SECURITY.md`](SECURITY.md). Do not open a public issue for one.
