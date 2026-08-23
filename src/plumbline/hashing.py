"""Content hashing for evidence bundles and judge configurations.

All hashes are SHA-256. The bundle hash is the dataset hash that appears in
every report; the judge configuration hash makes any change to scoring rules
visible in every report.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SHORT_ID_LEN = 12


def sha256_file(path: Path) -> str:
    """Hex digest of a file's raw bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bundle_digest(file_digests: dict[str, str]) -> str:
    """Combined bundle hash: sha256 over "<filename>=<hex>\\n" lines, sorted
    by filename. Deterministic regardless of insertion order."""
    lines = "".join(f"{name}={digest}\n" for name, digest in sorted(file_digests.items()))
    return sha256_text(lines)


def canonical_json(obj: object) -> str:
    """Canonical JSON used for hashing configuration objects."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def config_digest(config: dict[str, Any]) -> str:
    """Hash of a configuration dict (e.g., the judge configuration)."""
    return sha256_text(canonical_json(config))


def short_id(digest: str) -> str:
    return digest[:SHORT_ID_LEN]


def source_digest(package_dir: Path) -> str | None:
    """A hash of the harness's own source: sha256 over "<relpath>=<hex>\n"
    for every .py file under the package, sorted by path.

    Plumbline asks the systems it grades to say which bytes produced their
    evidence. `harness_version` does not answer that: it is a string somebody
    types, it stays `0.1.0.dev0` across every commit of a pre-release, and two
    runs from different code report the same value. This does answer it.

    Returns None — with the reason recorded next to it in the report — when
    the package is not readable as files on disk (a zipapp, for instance).
    Provenance that cannot be computed is reported as absent, never guessed.
    """
    package_dir = Path(package_dir)
    if not package_dir.is_dir():
        return None
    digests = {}
    for path in sorted(package_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digests[path.relative_to(package_dir).as_posix()] = sha256_file(path)
    if not digests:
        return None
    return sha256_text(
        "".join(f"{name}={digest}\n" for name, digest in sorted(digests.items())))
