"""The committed defect-injection proof must be true, and must be current.

`proof/matrix.md` claims that every enabled suite was observed failing on a
defect it exists to catch, and that the suites which should be indifferent
stayed passing. That claim is worth exactly as much as the last time anybody
checked it, so this checks it on every test run.

It is the slowest thing in the suite — it runs seventeen full audits over a
174-item bundle, about nine seconds — and that is the correct trade. A
fail-closed harness whose proof of being fail-closed is a stale committed file
has the problem it exists to prevent.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MATRIX_TOOL = REPO / "tools" / "defect_matrix.py"
PROOF = REPO / "proof"


def _load_tool():
    spec = importlib.util.spec_from_file_location("defect_matrix", MATRIX_TOOL)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: @dataclass resolves annotations
    # through sys.modules, and a module that is not there fails.
    sys.modules['defect_matrix'] = module
    spec.loader.exec_module(module)
    return module


class DefectMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = _load_tool()
        cls.matrix = cls.tool.build_matrix()

    def test_every_case_behaved_as_declared(self):
        broken = [(c["case"], c["problems"]) for c in self.matrix["cases"]
                  if not c["held"]]
        self.assertEqual(broken, [], f"cases that did not hold: {broken}")

    def test_every_enabled_suite_has_a_defect_case(self):
        self.assertEqual(self.matrix["suites_without_a_defect_case"], [])

    def test_every_suite_was_observed_failing_on_its_own_defect(self):
        for case in self.matrix["cases"]:
            if case["expect"] != self.tool.SUITE_FAILURE:
                continue
            with self.subTest(case=case["case"]):
                self.assertIn(case["suite"], case["suites_failed"])

    def test_the_control_run_passes(self):
        # Without this the whole matrix is meaningless: every suite would
        # "fail on its defect" because every suite was failing already.
        self.assertEqual(self.matrix["control"]["verdict"], "PASS")

    def test_the_committed_proof_is_current(self):
        rendered = self.tool.render_markdown(self.matrix)
        committed = (PROOF / "matrix.md").read_text(encoding="utf-8")
        self.assertEqual(
            rendered, committed,
            "proof/matrix.md is stale; run `python3 tools/defect_matrix.py`")

    def test_the_committed_json_proof_is_current(self):
        # The tool writes both files and its `--check` compares both, but
        # `--check` is on no path `make verify` reaches, and this file compared
        # only the Markdown. So `proof/matrix.json` -- the machine-readable
        # half, read by `tools/build_site.py`, `tools/check_claims.py`,
        # `tests/test_couplings.py` and `tests/test_self_application.py` -- was
        # a committed artifact standing in for a computation with nothing
        # regenerating it and comparing. Only the handful of fields those
        # readers happen to touch were held to anything, and a byte outside
        # them could have moved without a word said.
        rendered = self.tool.render_json(self.matrix)
        committed = (PROOF / "matrix.json").read_text(encoding="utf-8")
        self.assertEqual(
            rendered, committed,
            "proof/matrix.json is stale; run `python3 tools/defect_matrix.py`")

    # Determinism across processes is covered by
    # test_the_committed_proof_is_current: the committed file was written by a
    # previous run, so matching it byte for byte is the stronger check, and it
    # does not cost a second nine-second build.

    def test_a_case_that_does_not_hold_is_reported_rather_than_ignored(self):
        # The matrix is only useful if a suite that stopped failing would be
        # caught. Plant a defect and declare the wrong suite for it.
        wrong = self.tool.Case(
            id="deliberately-wrong",
            suite="privacy",
            defect="the interface loses its live region",
            must_catch="nothing: this case is deliberately mis-declared",
            mutate=self.tool._break_the_interface,
        )
        config = self.tool.load_config(self.tool.CONFIG)
        control = type("C", (), {"scores": self.matrix["control"]["scores"]})()
        result = self.tool._run_case(wrong, config.dataset_path, config, control)
        self.assertFalse(result["held"])
        self.assertTrue(any("privacy did not fail" in p
                            for p in result["problems"]), result["problems"])
        self.assertTrue(any("accessibility" in p for p in result["problems"]),
                        result["problems"])


if __name__ == "__main__":
    unittest.main()
