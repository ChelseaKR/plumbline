"""The history secret scan has to be able to fail on a leak that was revoked.

TruffleHog reports a finding under `verified` only when it asks the service and the service
says the credential is live. A credential that leaked and was then revoked answers no: it is
reported under `unverified` and never under `verified` -- and revoked is the normal end state
of a real incident. Somebody notices, the key is rotated, and the bytes stay in the history
forever. A full-history scan whose whole purpose is to find what was committed and taken back
out therefore could not fail on the very thing it exists for, and `security.yml` ran
`--only-verified` until 2026-09-06.

Measured on 2026-09-06 against a throwaway clone of this repository, with a real-shaped AWS
key planted in one commit and deleted in the next. The plant was confirmed present in history
and absent at HEAD before any of these numbers were trusted, and the key was deliberately not
AWS's documented example credential, which TruffleHog filters out under every tier:

    trufflehog --only-verified                        exit 0,   nothing reported
    trufflehog --results=verified,unknown,unverified  exit 183, 1 unverified secret
    gitleaks git .                                    exit 1,   2 leaks found

Widening the tier also reports two synthetic fixtures in `tests/test_network.py`: the same
`https://user:secret@example.test/chat` on two lines, the argument to
`test_credentials_in_the_url_are_refused`, whose entire point is that credentials in a URL are
rejected. `example.test` is a reserved TLD and cannot resolve. That is the whole of the noise,
and the answer to it is to switch off the DETECTOR that matched -- URI -- in the widened lane
and keep it armed in a second lane, not to leave the tier narrowed. `security.yml` now runs
both lanes in the `secrets` job, which makes it a strict superset of what that job checked
before.

So the invariants held here are:

* a history scan restricted to verified findings may never be the only history scan;
* some lane must report the `unverified` tier, and no lane may spell its selection
  `--only-verified`;
* every detector a widened lane switches off must stay armed in some other lane, Lob aside --
  Lob matches this repository's own test names under every tier and has no lane;
* the scanning binary is pinned by the `version:` input, not only by the action SHA;
* every history scan checks out the whole history and walks the whole tree.

The `secrets` job's NAME is deliberately left saying "verified only" even though it no longer
is. Branch protection on `main` requires that exact context, `enforce_admins` is true, and a
renamed required check never reports: every future pull request would wait forever. The name
is wrong on purpose until the protection rule is edited in the same change.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SECURITY = REPO / ".github" / "workflows" / "security.yml"

#: The name branch protection knows this job by. Changing the `name:` of a required check
#: leaves that check permanently unreported, which blocks every pull request rather than
#: failing one. Confirmed against `repos/ChelseaKR/plumbline/branches/main/protection` on
#: 2026-09-06, whose required contexts include this exact string.
REQUIRED_CHECK_NAME = "full-history secret scan (verified only)"


def workflow() -> str:
    assert SECURITY.exists(), f"{SECURITY} is missing"
    return SECURITY.read_text(encoding="utf-8")


def job(name: str) -> str:
    """One job's own block, comments above it excluded.

    Every assertion below looks inside this rather than at the whole file. The first version
    of this module asserted `"gitleaks git" in text`, and the comment introducing that job
    quotes the command it runs, so deleting the job entirely and leaving the explanation
    behind still passed. An assertion a comment can satisfy is not an assertion about the
    workflow.
    """
    text = workflow()
    match = re.search(
        rf"^  {re.escape(name)}:$(.*?)(?=^  [a-z0-9_-]+:$|\Z)", text, re.M | re.S
    )
    assert match, f"no `{name}` job in security.yml"
    return match.group(1)


#: The tier a revoked credential lands in. Its absence is the defect this module is named for.
REQUIRED_RESULT_TIER = "unverified"


def extra_args() -> list[str]:
    """Every `extra_args:` line in the workflow: one per scanning lane."""
    args = re.findall(r"^\s*extra_args:\s*(.+?)\s*$", workflow(), re.M)
    assert args, "no `extra_args:` line in security.yml; this guard can no longer see the flags"
    return args


def result_tiers() -> list[list[str]]:
    """The `--results=` selection of each lane that states one."""
    tiers = []
    for args in extra_args():
        match = re.search(r"--results=([\w,]+)", args)
        if match:
            tiers.append(match.group(1).split(","))
    return tiers


def excluded_detectors(args: str) -> set[str]:
    match = re.search(r"--exclude-detectors=([\w,]+)", args)
    return set(match.group(1).split(",")) if match else set()


class SecretScanningTests(unittest.TestCase):
    def test_the_workflow_is_read_at_all(self) -> None:
        """Every assertion below searches this text. A file that stopped being found, or an empty
        one, would make all of them pass over nothing."""
        text = workflow()
        assert len(text) > 500, "security.yml is too short to be the workflow"
        jobs = re.findall(r"^  ([a-z0-9_-]+):$", text, re.M)
        assert "secrets" in jobs, (
            f"no `secrets` job in security.yml; jobs found: {jobs}"
        )
        assert "gitleaks" in jobs, (
            f"no `gitleaks` job in security.yml; jobs found: {jobs}"
        )

    def test_a_verified_only_scan_is_never_the_only_history_scan(self) -> None:
        """The invariant. A scan restricted to verified findings cannot fail on a revoked
        credential, so it may run only alongside one that does not ask the service whether the
        key still works.

        Read from the `extra_args:` lines, not from the file. The workflow now explains in a
        comment why `--only-verified` is wrong, and a substring search over the whole document
        would find the explanation and conclude the flag was still in use.
        """
        if any(REQUIRED_RESULT_TIER in tiers for tiers in result_tiers()):
            # Some lane reports unverified results directly; nothing to compensate for.
            return
        assert "gitleaks git" in job("gitleaks"), (
            "security.yml restricts its history scan to verified findings and has no scan "
            "beside it that reports regardless of verification state. A credential that leaked "
            "and was revoked is reported as unverified, so nothing here could fail on it"
        )

    def test_no_lane_spells_its_selection_only_verified(self) -> None:
        """`--only-verified` and `--results=verified` select the same findings, but only one of
        them reads like a considered choice. Every lane states its tiers explicitly so that a
        reader can see at a glance which ones can fail on a revoked credential."""
        for args in extra_args():
            assert "--only-verified" not in args, (
                f"`--only-verified` cannot fail on a credential the provider has already "
                f"revoked, which is the case this scan exists for. Offending args: {args!r}"
            )
            assert re.search(r"--results=[\w,]+", args), (
                f"expected an explicit `--results=` tier list, got {args!r}"
            )

    def test_some_lane_reports_the_unverified_tier(self) -> None:
        """The defect this module is named for. Measured: `--only-verified`,
        `--results=verified` and `--results=verified,unknown` all exit 0 on a
        planted-then-deleted AWS key; adding `unverified` exits 183."""
        tiers = result_tiers()
        assert any(REQUIRED_RESULT_TIER in lane for lane in tiers), (
            f"no lane of the secret scan reports `{REQUIRED_RESULT_TIER}` results (found "
            f"{tiers}), so nothing in this workflow's TruffleHog job can fail on a credential "
            f"that leaked and was then revoked"
        )

    def test_every_detector_a_widened_lane_excludes_stays_armed_elsewhere(self) -> None:
        """The widened lane switches URI off because it matches two committed fixtures. That is
        only safe while another lane still runs URI, or the exclusion is a coverage loss wearing
        a false-positive fix's clothes.

        Lob is exempt: it matches this repository's own pytest function names under every tier
        and its verifier promotes them to verified, so no lane can usefully run it.
        """
        lanes = extra_args()
        widened = [a for a in lanes if REQUIRED_RESULT_TIER in a]
        others = [a for a in lanes if REQUIRED_RESULT_TIER not in a]

        needing_cover: set[str] = set()
        for args in widened:
            needing_cover |= excluded_detectors(args)
        needing_cover -= {"Lob"}

        for detector in sorted(needing_cover):
            assert any(detector not in excluded_detectors(a) for a in others), (
                f"{detector} is excluded from the widened lane and from every other lane too, "
                f"so nothing in this job can catch it any more. Keep the verified-results lane "
                f"that leaves it armed"
            )

    def test_the_scanning_binary_is_pinned_and_not_only_the_wrapper(self) -> None:
        """The action's `version:` input selects the image that scans
        (`ghcr.io/trufflesecurity/trufflehog:${VERSION}`) and defaults to `latest`, so the SHA on
        `uses:` pins only the wrapper. Dependabot edits the ref and never a `with:` input, so the
        two drift and each bump is a no-op that reads like an upgrade."""
        text = workflow()
        pinned = re.findall(
            r"trufflesecurity/trufflehog@[0-9a-f]{40}\s*#\s*v(\d+(?:\.\d+)*)", text
        )
        selected = re.findall(
            r"^\s*version:\s*\"?(\d+(?:\.\d+)*)\"?\s*$", text, re.M
        )
        assert pinned, "no SHA-pinned trufflehog ref carrying a `# vX.Y.Z` comment"
        assert selected, (
            "no `version:` input on any trufflehog step; the action then downloads `latest` and "
            "the SHA pin above it pins nothing that actually scans"
        )
        assert len(pinned) == len(selected), (
            f"{len(pinned)} pinned trufflehog ref(s) but {len(selected)} `version:` input(s); "
            f"every trufflehog step needs its own pinned version"
        )
        for ref_version, input_version in zip(pinned, selected):
            assert ref_version == input_version, (
                f"the action is pinned to v{ref_version} but `version: {input_version}` is what "
                f"downloads the scanner, so the bump to v{ref_version} changed nothing"
            )

    def test_the_scan_walks_the_whole_tree(self) -> None:
        """With path, base and head all unset the action exits on its own "BASE and HEAD commits
        are the same" guard, having scanned nothing, and reports success."""
        assert re.search(r"^\s*path:\s*\./\s*(?:#.*)?$", job("secrets"), re.M), (
            "`path: ./` is missing from the secrets job; the action would exit having scanned "
            "nothing and still go green"
        )

    def test_the_unverified_capable_scan_actually_fails_the_build(self) -> None:
        """A scanner that reports and exits 0 is a report, not a gate."""
        assert "--exit-code 1" in job("gitleaks"), (
            "the gitleaks history scan does not pass `--exit-code 1`, so a finding would be "
            "printed into the log and the job would still go green"
        )

    def test_every_history_scan_checks_out_the_whole_history(self) -> None:
        """A diff-scoped scan cannot see a secret added and removed within one branch, which is
        the shape this job exists for. Both scanning jobs must fetch the full history."""
        for name in ("secrets", "gitleaks"):
            assert "fetch-depth: 0" in job(name), (
                f"the `{name}` job does not check out the full history, so it is a diff scan "
                f"wearing a history scan's name"
            )

    def test_the_required_check_keeps_the_name_branch_protection_knows(self) -> None:
        """Not style. `main`'s protection lists this exact string as a required context, and a
        required check that never reports blocks every pull request rather than failing one."""
        text = workflow()
        assert f"name: {REQUIRED_CHECK_NAME}" in text, (
            f"the job named {REQUIRED_CHECK_NAME!r} is gone or renamed. Branch protection on "
            f"main requires that context by name; renaming it here leaves the check permanently "
            f"pending and no pull request can merge. Change the protection rule first"
        )

    def test_the_gitleaks_binary_is_pinned_and_checksum_verified(self) -> None:
        """The scan is only as trustworthy as the binary running it."""
        text = workflow()
        block = re.search(
            r"^  gitleaks:$(.*?)(?=^  [a-z0-9_-]+:$|\Z)", text, re.M | re.S
        )
        assert block
        body = block.group(1)
        assert re.search(r"GL=[0-9]+\.[0-9]+\.[0-9]+", body), (
            "the gitleaks version is not pinned"
        )
        assert "sha256sum --check --strict" in body, (
            "the downloaded gitleaks archive is not checksum-verified"
        )
        assert "set -euo pipefail" in body, (
            "without pipefail the checksum pipeline passes on a grep that matched nothing"
        )


if __name__ == "__main__":
    unittest.main()
