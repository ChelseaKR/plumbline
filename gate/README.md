# Gating a repository with Plumbline

Everything a consuming repository needs is in this directory. Two files get
copied; the rest are examples.

| File | What it is |
|---|---|
| `plumbline-gate.sh` | **Copy this.** The runner. Reads the pin, resolves the harness, runs the gate, exits with the gate's code. |
| `plumbline.pin.example` | **Copy this** as `plumbline.pin` and edit it. The single file that records which harness commit gates your repository. |
| `Makefile.example` | How local tooling calls the same runner. |
| `github-actions.example.yml` | How CI calls the same runner. |

## The shape of it

```
your-repo/
  plumbline.pin              # repo = ..., ref = <40-char commit>, config = ...
  plumbline-gate.sh          # copied from here, committed
  plumbline/
    target.toml              # your suites and floors
    bundle/                  # your evidence bundle
    baseline.json            # optional, the bar you are holding
```

```sh
./plumbline-gate.sh          # locally
./plumbline-gate.sh          # in CI — the identical command
```

## Why a pin file and not a dependency

Three properties, and each one is a thing that goes wrong otherwise.

**One file, both callers.** A laptop and a CI runner read the same
`plumbline.pin`. "Works locally, fails in CI" and its worse twin, "passes in
CI, fails locally", both come from two places recording two versions of the
tool. There is one place.

**An exact commit, not a range.** `ref` must be a full 40-character commit
hash; the runner rejects a branch or a tag. A moving ref means a green gate
today can quietly mean something else tomorrow, which is the opposite of what
an audit record is for. Bumping the pin is a reviewed diff, like any other
dependency upgrade.

**Resolved at run time, not installed.** The harness is not in your
`requirements.txt` or your lockfile. It is fetched into a cache directory when
the gate runs and verified to be at the pinned commit. The thing auditing your
repository is not a thing your repository's own dependency resolution can
quietly move.

## Fail closed

Every way this can go wrong exits **4** with a reason on stderr:

- no pin file, or a pin file missing `repo`, `ref` or `config`
- a `ref` that is not an exact commit hash
- `git` or Python missing
- the harness repository unreachable, or the pinned commit absent from it
- a resolved checkout that is not at the pinned commit
- a resolved checkout with no `src/`
- a model judge configured with `mode = "live"` — the gate does not make
  network calls. Record the judgments with `plumbline audit`, commit the
  judgment cache, and gate against it offline.

There is no path through the runner that skips the gate or reports success
without having run it. If the harness cannot be reached, the job fails. A gate
that could not run is not a gate that passed, and a build that treats those as
the same thing is a build with no gate.

## Exit codes

| Code | Meaning | What a CI job should do |
|---|---|---|
| 0 | Every enabled suite passed | merge |
| 1 | At least one suite failed | block; read the named suites |
| 2 | Usage error | fix the command |
| 3 | **Integrity refusal** — the evidence bundle did not verify, nothing was scored | block; the evidence is untrustworthy, which is not the same problem as a regression |
| 4 | Configuration or environment error, including an unresolvable harness | block; the gate did not run |
| 5 | **Internal error** — the harness crashed; nothing was measured | block; report the bug. This is deliberately not 1: exit 1 is a verdict, and no verdict was produced |

The separation of 1, 3, 4 and 5 is the point. "The target got worse", "the
evidence is untrustworthy", "the gate was misconfigured" and "the instrument
broke" need four different humans to do four different things, and a single
non-zero exit tells you which one only if you read the log. What they have in
common is that all of them block.

## Local harness development

`PLUMBLINE_SRC=/path/to/plumbline/src ./plumbline-gate.sh` bypasses resolution
and runs the working tree. It prints two loud lines to stderr saying the run is
not pinned and not reproducible. It is for developing the harness. CI must
never set it.

## Other environment overrides

| Variable | Default | Purpose |
|---|---|---|
| `PLUMBLINE_PIN_FILE` | `plumbline.pin` | Read the pin from somewhere else. |
| `PLUMBLINE_CACHE_DIR` | `.plumbline-cache` | Where resolved harness checkouts live. Cache it in CI keyed on the pin file. |
| `PLUMBLINE_PYTHON` | `python3` | Interpreter to run the harness with (3.11+). |

Arguments given to `plumbline-gate.sh` are passed through to the harness, so
`./plumbline-gate.sh --summary-file "$GITHUB_STEP_SUMMARY"` works.
