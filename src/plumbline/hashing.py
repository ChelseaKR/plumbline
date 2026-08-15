"""Content hashing for evidence bundles and judge configurations.

All hashes are SHA-256. The bundle hash is the dataset hash that appears in
every report; the judge configuration hash makes any change to scoring rules
visible in every report.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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


def config_digest(config: dict) -> str:
    """Hash of a configuration dict (e.g., the judge configuration)."""
    return sha256_text(canonical_json(config))


def short_id(digest: str) -> str:
    return digest[:SHORT_ID_LEN]
