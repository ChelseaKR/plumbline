# Publishing to PyPI for the first time

Plumbline has never been uploaded to PyPI. This page records what was checked
before the first upload, and the steps that only the maintainer can do. Nothing
here has been run against the real index, and `publish-pypi.yml` has not been
dispatched.

*Last verified: 2026-10-17. Recheck whenever `pyproject.toml`, `publish-pypi.yml`
or the PyPI Trusted Publishing screens change.*

## The name

The distribution name is `plumbline-eval`. The import name and the command stay
`plumbline`. On 2026-10-17 `https://pypi.org/pypi/plumbline-eval/json` returned
404, so the name was unclaimed; `plumbline` itself is held by an unrelated,
long-dormant package. A pending publisher (below) does not reserve a name, so
the name is only secured by the first successful upload.

## What was checked locally

`make dist-check` runs all of this in a temporary directory and leaves the
working tree untouched. It needs `uv` and network access for `uvx twine`, which
is why it is not part of `make verify`.

| Step | Result on 2026-10-17 |
|---|---|
| `uv build` produces an sdist and a wheel | `plumbline_eval-0.2.0.tar.gz` and `plumbline_eval-0.2.0-py3-none-any.whl` |
| `twine check --strict` on both files | passed, before and after the metadata change |
| Wheel contents | the `plumbline` package only, plus `LICENSE` and the dist-info; no datasets, tests or tools |
| Core metadata | name, version, summary, `License-Expression: Apache-2.0`, `Requires-Python: >=3.11`, classifiers, `Project-URL` for Homepage, Repository, Issues and Changelog |
| Install the wheel into a clean virtual environment | installed with no dependencies pulled in |
| Run the installed CLI | `plumbline --version`, `plumbline validate datasets/riverbend-demo` (integrity OK) and `plumbline audit --config examples/riverbend.toml` (all implemented suites scored, exit 0) |

The metadata change that came out of this check: before it, the wheel had **no
`Project-URL` entries**. `twine check` passes in that state, because missing
links are not malformed metadata. A published version is immutable, so a first
upload without them would leave the PyPI page without links to the repository,
the issue tracker or the changelog until a later version replaced it. This is
what happened to `gauntlet-evals` 0.2.0. `tests/test_packaging_metadata.py` now
fails if the links go missing, if the declared version differs from
`plumbline.__version__`, or if the README or distribution name changes.

## Decide which tag to publish from

Do not publish from `v0.2.0`.

- The `v0.2.0` tree has no `[project.urls]`, so its wheel would carry the defect
  described above, permanently.
- `publish-pypi.yml` runs from the ref it is dispatched on. At `v0.2.0` that file
  predates the `verify-tag` job, so the signature gate would not run.
- `v0.2.0` is on the `GRANDFATHERED_TAGS` list because it was cut without a
  signature.

The unreleased section of `CHANGELOG.md` states that the next release is a MINOR
bump, `0.3.0`, because it contains a breaking change. Publishing from a new tag
fits that plan. The release commit is an ordinary change and the repository's
tests will say what has to move with it:

1. Set the new version in `pyproject.toml` and `src/plumbline/__init__.py`.
2. Move the `[Unreleased]` entries under a dated `## [X.Y.Z]` heading and add its
   link reference at the foot of `CHANGELOG.md`.
3. Regenerate what depends on the source and version: `python3 tools/build_sbom.py`,
   the committed audit and baseline under `audits/` and `baselines/` (see
   `CONTRIBUTING.md`), `proof/matrix.md`, and the site (`python3 tools/build_site.py`).
4. Run `make verify` and `make dist-check` on that commit.
5. Merge it, then create a **signed, annotated** tag on the merged commit, with a
   key listed in `.github/allowed_signers`:

   ```sh
   git tag -s vX.Y.Z -m "plumbline vX.Y.Z"
   git push origin vX.Y.Z
   ```

Pushing the tag starts `release.yml`, which verifies the signature, signs the
SBOM and creates a GitHub Release. It does not upload to PyPI. That is a separate
workflow, started by hand, below.

## Register the trusted publisher on PyPI

Trusted Publishing lets the workflow upload with a short-lived OIDC credential,
so no API token exists to leak or rotate. It needs a person logged in to a PyPI
account with two-factor authentication.

1. Sign in at <https://pypi.org/>.
2. Open **Your account**, then **Publishing**, then **Add a new pending
   publisher**. A pending publisher is what allows the first upload to create the
   project.
3. Enter exactly these values:

   | Field | Value |
   |---|---|
   | PyPI project name | `plumbline-eval` |
   | Owner | `ChelseaKR` |
   | Repository name | `plumbline` |
   | Workflow name | `publish-pypi.yml` |
   | Environment name | `pypi` |

4. Save. The values must match the workflow character for character. A mismatch
   fails at upload with an `invalid-publisher` error, which is what happened on
   the first `gauntlet-evals` attempt.

## Create the GitHub environment

`publish-pypi.yml` declares `environment: pypi`.

1. In the repository, open **Settings**, then **Environments**, then **New
   environment**, and name it `pypi`.
2. Optionally add a required reviewer, so that the upload pauses for a
   confirmation after the workflow is dispatched. For a single maintainer this is
   a confirmation prompt and not a second reviewer.

## Dispatch the workflow

1. Open **Actions**, then **publish-pypi**, then **Run workflow**.
2. In **Use workflow from**, choose the **tag** created above, not a branch. A
   branch makes `verify-tag` fail, by design.
3. Type `publish` in the confirmation box and run it.

The jobs run in order: `verify-tag`, then `build` (which now ends with
`twine check --strict`), then `publish`, which attests build provenance and
uploads.

## After the upload

- `pip install plumbline-eval==X.Y.Z` in a clean environment, then
  `plumbline --version`.
- Open <https://pypi.org/project/plumbline-eval/> and confirm the four project
  links and the rendered README.
- `gh attestation verify plumbline_eval-X.Y.Z-py3-none-any.whl --owner ChelseaKR`
  on the downloaded wheel.
- Update the README sentence that says the package is not yet on PyPI, and the
  Release & Versioning row, in a follow-up change. Those sentences are checked by
  tests and should only change once the upload has happened.

## If something is wrong after upload

A released file cannot be replaced or edited. The remedies are to yank the
version on PyPI, which keeps it installable by exact pin but hides it from
resolvers, and to publish a new version.

## Not done by this change

- No version was bumped, no tag was created, and no workflow was dispatched.
- The pending publisher and the `pypi` environment were not created; both need
  the maintainer's accounts.
- The README still says the package is not on PyPI, which remains true.
