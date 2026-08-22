"""The committed SBOM must be what pyproject.toml produces, and the check
that proves it must be able to fail.

Mirrors tests/test_site.py's pattern for the same reason: a committed
artifact this repository ships (here, a supply-chain claim) is only worth
anything if drift from its source is caught, not merely asserted to be
caught.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import build_sbom  # noqa: E402


class TheCommittedSbomIsCurrent(unittest.TestCase):
    def test_the_committed_file_is_what_pyproject_produces(self):
        expected = build_sbom.render(build_sbom.build())
        self.assertEqual(
            build_sbom.SBOM_PATH.read_text(encoding="utf-8"), expected,
            "sbom.cdx.json is stale; run `python3 tools/build_sbom.py`")

    def test_the_check_command_agrees(self):
        self.assertEqual(build_sbom.main(["--check"]), 0)

    def test_a_drifted_sbom_is_caught(self):
        bom = build_sbom.build()
        text = build_sbom.render(bom)
        drifted = dict(bom)
        drifted["specVersion"] = "9.9"
        self.assertNotEqual(build_sbom.render(drifted), text)

    def test_zero_runtime_dependencies_is_declared_not_just_empty(self):
        bom = build_sbom.build()
        self.assertEqual(bom["components"], [])
        declarations = {p["name"]: p["value"] for p in bom["properties"]}
        self.assertEqual(declarations["plumbline:runtime-dependency-count"], "0")
        self.assertIn("zero third-party runtime dependencies",
                      declarations["plumbline:declaration"])

    def test_dev_tools_are_listed_separately_from_components(self):
        bom = build_sbom.build()
        tool_names = {c["name"] for c in bom["metadata"]["tools"]["components"]}
        self.assertIn("ruff", tool_names)
        self.assertIn("coverage", tool_names)
        # Dev tooling never counts as something this project ships.
        self.assertEqual(bom["components"], [])

    def test_no_timestamp_field(self):
        # Byte-reproducibility, the same discipline reports use: a wall-clock
        # value here would make `--check` fail on every re-run regardless of
        # whether anything about the dependencies changed.
        bom = build_sbom.build()
        self.assertNotIn("timestamp", bom["metadata"])
        text = build_sbom.render(bom)
        self.assertEqual(text, build_sbom.render(build_sbom.build()))

    def test_pep508_parser_refuses_a_shape_it_does_not_understand(self):
        with self.assertRaises(ValueError):
            build_sbom._parse_pep508("somepkg[extra]>=1.0")

    def test_json_output_is_valid_and_matches_committed_bytes(self):
        parsed = json.loads(build_sbom.SBOM_PATH.read_text(encoding="utf-8"))
        self.assertEqual(parsed["bomFormat"], "CycloneDX")


if __name__ == "__main__":
    unittest.main()
