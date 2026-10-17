"""The metadata PyPI will show is declared before the first upload, not after.

A published release on PyPI is immutable. The sibling project gauntlet-evals
uploaded 0.2.0 with no `Project-URL` entries because `[project.urls]` merged
after its tag was cut, and its 0.2.0 page has had no link to the repository, the
issue tracker or the changelog ever since; only a new version could repair it.
`twine check` does not catch that, because absent links are not malformed
metadata. This is the check that does.

What is held: the four links a reader arriving from `pip` needs exist, are
HTTPS, and point at this project; the version `pyproject.toml` declares is the
version the package reports; the README PyPI will render exists; and the
distribution name is the one the publish workflow and the SBOM expect.

Each rule is a function over a plain mapping so the negative controls can hand
it a defective one. A check that has only ever seen good input has not shown it
can fail.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path
from urllib.parse import urlparse

from plumbline import __version__

REPO = Path(__file__).resolve().parent.parent

REQUIRED_URLS = ("Homepage", "Repository", "Issues", "Changelog")
# Hosts a link may legitimately name: the repository and its Pages site.
ALLOWED_HOSTS = {"github.com", "chelseakr.github.io"}
EXPECTED_NAME = "plumbline-eval"


def url_problems(project: dict) -> list[str]:
    problems: list[str] = []
    urls = project.get("urls")
    if not isinstance(urls, dict) or not urls:
        return ["[project.urls] is missing: the PyPI page would carry no links"]
    for label in REQUIRED_URLS:
        if label not in urls:
            problems.append(f"[project.urls] has no {label}")
    for label, value in urls.items():
        parsed = urlparse(value)
        if parsed.scheme != "https":
            problems.append(f"{label} is not an https URL: {value!r}")
        elif parsed.hostname not in ALLOWED_HOSTS:
            problems.append(f"{label} names an unexpected host: {parsed.hostname!r}")
        elif parsed.hostname == "github.com" and not parsed.path.startswith("/ChelseaKR/plumbline"):
            problems.append(f"{label} does not point at this repository: {value!r}")
    return problems


def version_problems(project: dict, package_version: str) -> list[str]:
    declared = project.get("version")
    if declared != package_version:
        return [
            f"pyproject.toml declares version {declared!r} but plumbline.__version__ is "
            f"{package_version!r}; a wheel would tell pip one number and `import plumbline` another"
        ]
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(declared)):
        return [f"version {declared!r} is not a plain MAJOR.MINOR.PATCH number"]
    return []


def readme_problems(project: dict, root: Path) -> list[str]:
    readme = project.get("readme")
    if not isinstance(readme, str):
        return ["no readme is declared, so PyPI would show an empty description"]
    if not (root / readme).is_file():
        return [f"readme {readme!r} does not exist"]
    return []


def name_problems(project: dict) -> list[str]:
    if project.get("name") != EXPECTED_NAME:
        return [f"distribution name is {project.get('name')!r}, expected {EXPECTED_NAME!r}"]
    return []


def _project() -> dict:
    with (REPO / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


class TheCommittedMetadataIsPublishReady(unittest.TestCase):
    def test_project_urls_are_declared_and_point_at_this_project(self):
        self.assertEqual(url_problems(_project()), [])

    def test_the_declared_version_is_the_version_the_package_reports(self):
        self.assertEqual(version_problems(_project(), __version__), [])

    def test_the_readme_pypi_renders_exists(self):
        self.assertEqual(readme_problems(_project(), REPO), [])

    def test_the_distribution_name_is_the_one_the_publish_path_expects(self):
        self.assertEqual(name_problems(_project()), [])

    def test_the_license_is_declared_as_an_spdx_expression(self):
        self.assertEqual(_project().get("license"), "Apache-2.0")


class TheChecksCanFail(unittest.TestCase):
    """Negative controls: each rule must go red on the defect it exists for."""

    def test_missing_urls_table_is_reported(self):
        project = dict(_project())
        project.pop("urls", None)
        self.assertTrue(url_problems(project))

    def test_a_missing_link_is_named(self):
        project = dict(_project())
        project["urls"] = {k: v for k, v in project["urls"].items() if k != "Issues"}
        self.assertIn("[project.urls] has no Issues", url_problems(project))

    def test_a_plain_http_link_is_reported(self):
        project = dict(_project())
        project["urls"] = {**project["urls"], "Homepage": "http://chelseakr.github.io/plumbline/"}
        self.assertTrue(any("https" in p for p in url_problems(project)))

    def test_a_link_to_another_repository_is_reported(self):
        project = dict(_project())
        project["urls"] = {**project["urls"], "Repository": "https://github.com/ChelseaKR/gauntlet"}
        self.assertTrue(any("this repository" in p for p in url_problems(project)))

    def test_a_link_to_an_unexpected_host_is_reported(self):
        project = dict(_project())
        project["urls"] = {**project["urls"], "Homepage": "https://example.invalid/"}
        self.assertTrue(any("unexpected host" in p for p in url_problems(project)))

    def test_a_version_that_disagrees_with_the_package_is_reported(self):
        self.assertTrue(version_problems({"version": "0.2.0"}, "0.1.0"))

    def test_a_missing_readme_is_reported(self):
        self.assertTrue(readme_problems({"readme": "NO-SUCH-FILE.md"}, REPO))
        self.assertTrue(readme_problems({}, REPO))

    def test_a_different_distribution_name_is_reported(self):
        self.assertTrue(name_problems({"name": "plumbline"}))


if __name__ == "__main__":
    unittest.main()
