"""Build a CycloneDX SBOM from `pyproject.toml` — the file that already names
this project's supply-chain surface, read the same way `config.py` reads a
target's TOML: stdlib `tomllib`, nothing else.

The Security & Supply-Chain conformance row states the position this SBOM
makes checkable rather than merely asserted: "no third-party runtime
dependency, so the largest supply-chain surface does not exist here." The
bom this writes has an empty `components` list, on purpose — and says so in
a `plumbline:declaration` property next to it, rather than leaving a reader
to infer "empty" means "checked and clean" from silence. An SBOM with
nothing in it and no comment explaining why would be exactly the kind of
check that cannot go red this project argues against everywhere else: it
would read identically whether nobody had looked, or somebody had looked and
found nothing. Development-only tooling (`ruff`, `coverage` — the
`dependency-groups.dev` list `CONTRIBUTING.md` already says "is never
imported by `plumbline`") is listed separately, under `metadata.tools`,
never under `components`: it does not ship, so it is not part of what this
SBOM is a bill of materials *for*.

**No timestamp.** `metadata.timestamp` is CycloneDX-optional, and every
report this harness writes elsewhere carries none either — "a report must be
a pure function of its inputs," so identical inputs give byte-identical
output. The same holds here: this file's `--check` is a byte comparison, the
same discipline `tools/build_site.py` and `tools/defect_matrix.py --check`
already apply to their own committed artifacts, and it would not be one if a
wall-clock value changed on every run.

    python3 tools/build_sbom.py            # write sbom.cdx.json
    python3 tools/build_sbom.py --check    # rebuild and compare, do not write
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"
SBOM_PATH = REPO / "sbom.cdx.json"

CYCLONEDX_SPEC_VERSION = "1.5"

_OPERATORS = (">=", "<=", "==", "~=", "!=", ">", "<")


def _parse_pep508(spec: str) -> dict:
    """A minimal PEP 508 requirement (`name>=1.2`) as a CycloneDX component.

    Every runtime and dev dependency in this project's own pyproject.toml is
    a plain `name<op>version` string with no extras and no environment
    marker, so this does not need — and does not attempt — a general PEP 508
    parser. A requirement shaped any other way is refused rather than
    silently mis-split, so a future dependency this cannot parse fails the
    build instead of vanishing from the SBOM unlisted.
    """
    for op in _OPERATORS:
        if op in spec:
            name, version = spec.split(op, 1)
            name = name.strip()
            _check_plain_name(name, spec)
            return {
                "type": "application",
                "name": name,
                "version": f"{op}{version.strip()}",
            }
    name = spec.strip()
    _check_plain_name(name, spec)
    return {"type": "application", "name": name}


def _check_plain_name(name: str, spec: str) -> None:
    if not name or any(c in name for c in "[]; "):
        raise ValueError(
            f"{spec!r} is not a plain 'name<op>version' requirement this "
            f"minimal parser understands; extend it rather than guessing")


def build() -> dict:
    with open(PYPROJECT, "rb") as f:
        raw = tomllib.load(f)
    project = raw["project"]
    name = project["name"]
    version = project["version"]
    runtime_deps = sorted(project.get("dependencies", []))
    dev_deps = sorted(raw.get("dependency-groups", {}).get("dev", []))

    declaration = (
        "zero third-party runtime dependencies; development-only tooling is "
        "listed under metadata.tools, never under components"
        if not runtime_deps else
        "runtime dependencies are present; see components"
    )

    component = {
        "type": "application",
        "name": name,
        "version": version,
        "purl": f"pkg:pypi/{name}@{version}",
    }
    license_field = project.get("license")
    license_id = (license_field.get("text") if isinstance(license_field, dict)
                 else license_field)
    if license_id:
        component["licenses"] = [{"license": {"id": license_id}}]

    return {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": component,
            "tools": {"components": [_parse_pep508(d) for d in dev_deps]},
        },
        "components": [_parse_pep508(d) for d in runtime_deps],
        "properties": [
            {"name": "plumbline:runtime-dependency-count",
             "value": str(len(runtime_deps))},
            {"name": "plumbline:declaration", "value": declaration},
        ],
    }


def render(bom: dict) -> str:
    # sort_keys, not the insertion order `build()` used: unlike a report's
    # `build_report`, there is no reader-facing narrative order to preserve
    # here, and a fully sorted, canonical rendering is the simpler
    # `--check` invariant to hold across edits to this file.
    return json.dumps(bom, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a CycloneDX SBOM from pyproject.toml.")
    parser.add_argument("--check", action="store_true",
                        help="rebuild and compare against the committed "
                             "SBOM; do not write")
    args = parser.parse_args(argv)

    text = render(build())

    if args.check:
        current = (SBOM_PATH.read_text(encoding="utf-8")
                  if SBOM_PATH.is_file() else None)
        if current != text:
            print(f"{SBOM_PATH.relative_to(REPO)} is not what "
                  f"pyproject.toml produces; run "
                  f"`python3 tools/build_sbom.py`", file=sys.stderr)
            return 1
        print(f"{SBOM_PATH.relative_to(REPO)} is current")
        return 0

    SBOM_PATH.write_text(text, encoding="utf-8")
    print(f"wrote: {SBOM_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
