"""The release-tag gate has to be able to fail.

`.github/verify-release-tag.sh` decides whether a tag may publish a GitHub
Release and a wheel to PyPI under this project's name. CONTRIBUTING.md's rule
for a new gate is the rule this file follows: not only a test proving it passes
on good input, but tests proving it refuses a wrong key, a missing signature,
and a subject that changed after it was signed. tests/test_signing.py does that
for report signatures. This does it for release tags.

So nothing here reads the script. It runs it, against tags built to be wrong in
each of the ways a release tag can be wrong: unsigned, lightweight, signed by a
key nobody trusts, absent, and correct but naming a different commit than the
one being built.

The keys are generated per run into a temporary directory and thrown away with
it. The maintainer's real signing key is never read, copied, or invoked: the
passing case proves the script accepts a signature from whichever key the
allowed-signers file names, and inside the temporary repository that file names
a throwaway key.

Git configuration is neutralised deliberately. Written on a machine carrying
`tag.gpgSign = true` in `~/.gitconfig`, git silently signed the tag that exists
to be unsigned, and "an unsigned tag is rejected" passed while testing nothing
of the kind. A negative control that does not apply reads exactly like a pass,
so the fixture asserts each malformed tag is really malformed before any case
uses it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / ".github" / "verify-release-tag.sh"
ALLOWED_SIGNERS = REPO / ".github" / "allowed_signers"
WORKFLOWS = (
    REPO / ".github" / "workflows" / "release.yml",
    REPO / ".github" / "workflows" / "publish-pypi.yml",
)

# The tags cut before the gate existed, which it therefore does not verify.
# v0.2.0 was tagged with `git tag -a` rather than `-s`, which the README's
# Release & Versioning row has recorded as a gap since it was cut. v0.1.0 is
# signed and verifies against the committed key, so it is not exempted.
#
# Named here as well as in both workflows so that changing one without the
# others fails: a test that exempts a different list than CI exempts is a test
# of a gate nobody runs.
GRANDFATHERED = ("v0.2.0",)

# Git with no global or system configuration, so nothing in a developer's own
# ~/.gitconfig can decide the outcome of a case below.
NEUTRAL_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
    "PATH": os.environ.get("PATH", ""),
    "HOME": os.environ.get("HOME", ""),
}

SIGNATURE = "BEGIN SSH SIGNATURE"


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True, env=NEUTRAL_ENV,
    ).stdout.strip()


class Fixture:
    """A throwaway repository holding one tag of each interesting shape."""

    def __init__(self, directory):
        self.repo = directory / "repo"
        self.repo.mkdir()
        keys = directory / "keys"
        keys.mkdir()
        self.trusted = keys / "trusted"
        self.attacker = keys / "attacker"
        for key in (self.trusted, self.attacker):
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", key.name, "-f", str(key)],
                check=True, capture_output=True, env=NEUTRAL_ENV,
            )

        git(self.repo, "init", "-q", "-b", "main")
        for name, value in (
            ("user.email", "throwaway@example.invalid"),
            ("user.name", "Throwaway"),
            ("gpg.format", "ssh"),
            ("commit.gpgSign", "false"),
            ("tag.gpgSign", "false"),
            ("user.signingkey", str(self.trusted) + ".pub"),
        ):
            git(self.repo, "config", name, value)

        github = self.repo / ".github"
        github.mkdir()
        algorithm, material = self.trusted.with_suffix(".pub").read_text("utf-8").split()[:2]
        (github / "allowed_signers").write_text(
            'throwaway@example.invalid namespaces="git" '
            "{} {}\n".format(algorithm, material),
            encoding="utf-8",
        )
        (github / "verify-release-tag.sh").write_bytes(SCRIPT.read_bytes())
        git(self.repo, "add", ".github/allowed_signers", ".github/verify-release-tag.sh")
        git(self.repo, "commit", "-q", "-m", "fixture")
        self.head = git(self.repo, "rev-parse", "HEAD")

        git(self.repo, "tag", "-s", "v9.0.0", "-m", "signed by the trusted key")
        git(self.repo, "tag", "-a", "v9.0.1", "-m", "annotated, never signed")
        git(self.repo, "tag", "v9.0.2")
        git(self.repo, "-c", "user.signingkey={}.pub".format(self.attacker),
            "tag", "-s", "v9.0.3", "-m", "signed by a key nobody trusts")
        git(self.repo, "tag", "-a", GRANDFATHERED[0], "-m", "stands in for real history")

    def run(self, **environment):
        env = dict(NEUTRAL_ENV)
        env["ALLOWED_SIGNERS"] = ".github/allowed_signers"
        env.update(environment)
        return subprocess.run(
            ["bash", ".github/verify-release-tag.sh"],
            cwd=self.repo, capture_output=True, text=True, env=env,
        )


class GateCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform == "win32":  # pragma: no cover - the gate runs on ubuntu
            raise unittest.SkipTest("exercises the POSIX bash gate with ssh-keygen")
        cls.directory = TemporaryDirectory()
        cls.fixture = Fixture(Path(cls.directory.name))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "directory"):
            cls.directory.cleanup()


class TheGateAcceptsWhatItShould(GateCase):
    def test_the_fixture_is_in_the_shape_every_case_below_assumes(self):
        repo = self.fixture.repo
        self.assertEqual(git(repo, "cat-file", "-t", "v9.0.2"), "commit",
                         "v9.0.2 must be a lightweight tag")
        for annotated in ("v9.0.0", "v9.0.1", "v9.0.3", GRANDFATHERED[0]):
            self.assertEqual(git(repo, "cat-file", "-t", annotated), "tag", annotated)
        for signed in ("v9.0.0", "v9.0.3"):
            self.assertIn(SIGNATURE, git(repo, "cat-file", "-p", signed), signed)
        for unsigned in ("v9.0.1", GRANDFATHERED[0]):
            self.assertNotIn(SIGNATURE, git(repo, "cat-file", "-p", unsigned), unsigned)

    def test_a_signed_tag_naming_the_built_commit_passes(self):
        result = self.fixture.run(RELEASE_TAG="v9.0.0", EXPECT_COMMIT=self.fixture.head)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verified", result.stdout)

    def test_a_dispatch_from_a_tag_ref_resolves_that_tag(self):
        # publish-pypi.yml has no release event to read a tag from: a
        # dispatched ref is the only source it has, so this is its whole path.
        result = self.fixture.run(REF_TYPE="tag", REF_NAME="v9.0.0",
                                  EXPECT_COMMIT=self.fixture.head)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_named_grandfathered_tag_is_skipped_and_says_so(self):
        result = self.fixture.run(RELEASE_TAG=GRANDFATHERED[0],
                                  EXPECT_COMMIT=self.fixture.head,
                                  GRANDFATHERED_TAGS=" ".join(GRANDFATHERED))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("predates", result.stdout)


class TheGateRejectsWhatItShould(GateCase):
    def rejects(self, expected, **environment):
        result = self.fixture.run(**environment)
        self.assertNotEqual(
            result.returncode, 0,
            "this would have published:\n{}\n{}".format(result.stdout, result.stderr),
        )
        self.assertIn(expected, result.stdout + result.stderr)

    def test_an_unsigned_annotated_tag_is_refused(self):
        self.rejects("not signed by a key listed",
                     RELEASE_TAG="v9.0.1", EXPECT_COMMIT=self.fixture.head)

    def test_a_lightweight_tag_is_refused(self):
        self.rejects("not an annotated tag object",
                     RELEASE_TAG="v9.0.2", EXPECT_COMMIT=self.fixture.head)

    def test_a_tag_signed_by_an_untrusted_key_is_refused(self):
        self.rejects("not signed by a key listed",
                     RELEASE_TAG="v9.0.3", EXPECT_COMMIT=self.fixture.head)

    def test_a_dispatch_from_a_branch_publishes_nothing(self):
        self.rejects("No release tag could be resolved",
                     REF_TYPE="branch", REF_NAME="main", EXPECT_COMMIT=self.fixture.head)

    def test_a_tag_that_does_not_exist_is_refused(self):
        self.rejects("does not exist", RELEASE_TAG="v9.9.9",
                     EXPECT_COMMIT=self.fixture.head)

    def test_a_verified_tag_that_names_another_commit_is_refused(self):
        # Signature verification on its own passes here. Without this the gate
        # would prove that some tag was signed while the build ran from
        # something else, which is a check that cannot fail on the thing it
        # exists to catch.
        self.rejects("Refusing to publish", RELEASE_TAG="v9.0.0", EXPECT_COMMIT="0" * 40)

    def test_the_grandfather_list_cannot_be_widened_into_a_pattern(self):
        for widened in ("v*", "v9.0.1*", "*"):
            with self.subTest(entry=widened):
                self.rejects("is not a literal", RELEASE_TAG="v9.0.1",
                             EXPECT_COMMIT=self.fixture.head, GRANDFATHERED_TAGS=widened)

    def test_an_empty_allowed_signers_file_cannot_wave_a_tag_through(self):
        (self.fixture.repo / ".github" / "empty_signers").write_text("", encoding="utf-8")
        self.rejects("missing or empty", RELEASE_TAG="v9.0.0",
                     EXPECT_COMMIT=self.fixture.head,
                     ALLOWED_SIGNERS=".github/empty_signers")


class BothWorkflowsActuallyUseTheGate(unittest.TestCase):
    """The script above can be perfect and unreferenced."""

    def test_both_publishing_workflows_run_the_script(self):
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                self.assertIn(".github/verify-release-tag.sh",
                              workflow.read_text(encoding="utf-8"))

    def test_nothing_that_publishes_runs_without_it(self):
        # A verification job nothing depends on reports and never blocks,
        # which is the same shape as no job at all. The jobs named here are
        # the ones that create a GitHub Release or upload to PyPI.
        publishing = {
            "release.yml": ("release:",),
            "publish-pypi.yml": ("build:", "publish:"),
        }
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            for job in publishing[workflow.name]:
                with self.subTest(workflow=workflow.name, job=job):
                    block = text[text.index("\n  " + job):]
                    header = block[:block.index("steps:")]
                    self.assertIn("verify-tag", header)

    def test_the_pypi_build_uses_the_commit_the_verified_tag_names(self):
        text = (REPO / ".github" / "workflows" / "publish-pypi.yml").read_text(encoding="utf-8")
        self.assertIn("ref: ${{ needs.verify-tag.outputs.commit }}", text)

    def test_both_workflows_grandfather_exactly_what_this_file_does(self):
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding="utf-8")
            declared = re.search(r'GRANDFATHERED_TAGS:\s*"([^"]*)"', text)
            with self.subTest(workflow=workflow.name):
                self.assertIsNotNone(declared, "no GRANDFATHERED_TAGS")
                self.assertEqual(tuple(declared.group(1).split()), GRANDFATHERED)

    def test_the_committed_allowed_signers_names_a_key(self):
        lines = [line for line in ALLOWED_SIGNERS.read_text("utf-8").splitlines()
                 if line.strip() and not line.startswith("#")]
        self.assertTrue(lines, "allowed_signers is empty")
        self.assertTrue(all("ssh-" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
