"""The history secret scan has to be able to fail on a leak that was revoked.

`security.yml`'s TruffleHog job runs with `--only-verified`, which reports a finding only
when it asks the service and the service says the credential is live. A credential that
leaked and was then revoked answers no. It is reported under `unverified` and never under
`verified` -- and revoked is the normal end state of a real incident: somebody notices, the
key is rotated, and the bytes stay in the history forever. A full-history scan whose whole
purpose is to find what was committed and taken back out could therefore not fail on the very
thing it exists for.

Measured on 2026-09-06 against a throwaway clone of this repository, with a real-shaped AWS
key planted in one commit and deleted in the next. The plant was confirmed present in history
and absent at HEAD before any of these numbers were trusted, and the key was deliberately not
AWS's documented example credential, which TruffleHog filters out under every tier:

    trufflehog --only-verified                        exit 0,   nothing reported
    trufflehog --results=verified,unknown,unverified  exit 183, 1 unverified secret
    gitleaks git .                                    exit 1,   2 leaks found

Adding the unverified tier to the TruffleHog job would close the hole and would also report
two synthetic fixtures in `tests/test_network.py`, one of them the URL in
`test_credentials_in_the_url_are_refused` whose entire point is that credentials in a URL are
rejected. That job would be red on this repository today for no real finding. gitleaks matches
on pattern rather than on verification, so it catches the planted key and reports nothing on
this history as it stands.

So the invariant this file holds is not "use one tool". It is: **a history scan restricted to
verified findings may never be the only history scan.**
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
        """The invariant. `--only-verified` cannot fail on a revoked credential, so it may run
        only alongside a scan that does not ask the service whether the key still works."""
        text = workflow()
        if "--only-verified" not in text:
            # The restriction is gone; there is nothing to compensate for.
            return
        assert "gitleaks git" in job("gitleaks"), (
            "security.yml restricts its history scan to verified findings and has no scan "
            "beside it that reports regardless of verification state. A credential that leaked "
            "and was revoked is reported as unverified, so nothing here could fail on it"
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
