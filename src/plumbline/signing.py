"""Detached report signatures: a shared-secret attestation of who produced a
report, layered on top of the tamper-evident seal `report.py` already writes.

Every report already carries `report_sha256` — a sha256 with no secret in
it, so anyone who can read the file can recompute it. That is tamper
evidence: it proves the copy in front of you is the copy that was written.
`plumbline verify` says so today, in as many words: "this is tamper evidence,
not authentication ... vouching for WHO produced a report needs a signature
over these bytes, which Plumbline does not issue." This module is that
signature, with the same discipline about stating its own limits that the
rest of the harness applies to what it measures.

**What this is not.** Public-key signing — an ed25519 or RSA signature a
third party could verify without holding a secret — needs either a
hand-rolled asymmetric-crypto implementation, which this project will not
ship (rolling your own crypto is exactly the kind of confident,
unverifiable-until-it-fails artifact the harness argues against everywhere
else), or a third-party runtime dependency, which the Security &
Supply-Chain conformance row treats as the harness's whole point to avoid.
`docs/adr/0002-shared-secret-report-signatures.md` records the tradeoff.

**What this is.** HMAC-SHA256 over the report's own seal, using a secret
both the signer and every intended verifier hold. It proves the signer
possessed the key at signing time and the seal has not moved since — the
same "who", but attributable only to the holders of that one key, not to the
public at large. A reader without the key learns nothing from a signature
file except that one exists and which key id it names. This is
authentication between parties who already share a secret, not a public
attestation; a reader who needs the latter still cannot get it from this
harness, and nothing here should be read as claiming otherwise.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from .hashing import short_id
from .report import verify_report

SIGNATURE_FILENAME = "report.sig"
SIGNATURE_FORMAT = "plumbline-signature"
ALGORITHM = "hmac-sha256"

# A key this short is guessable by brute force well within the lifetime of
# anything it would protect; refusing it here is cheaper than explaining a
# forged signature later.
MIN_KEY_BYTES = 16


class SigningError(Exception):
    """A signature could not be produced or checked (configuration error)."""


class SignatureMismatchError(SigningError):
    """A signature file exists and is well-formed, but does not attest to
    this report: wrong key, an edited signature file, or a signature made
    for different bytes entirely. Treated the same as a seal mismatch —
    refuse rather than warn, because a signature nobody checked is exactly
    the seal-shaped decoration `plumbline verify` already exists to avoid.
    """


def read_key(path: Path) -> bytes:
    """A shared-secret key from a file: raw bytes, trailing whitespace and a
    trailing newline stripped so the same key works whether or not an editor
    added one."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise SigningError(f"unreadable key file {path}: {e}") from e
    key = data.strip()
    if not key:
        raise SigningError(f"key file {path} is empty")
    if len(key) < MIN_KEY_BYTES:
        raise SigningError(
            f"key file {path} holds {len(key)} byte(s); a key shorter than "
            f"{MIN_KEY_BYTES} is guessable, refusing to sign or verify with it"
        )
    return key


def key_id(key: bytes) -> str:
    """A short, one-way fingerprint of a key: identifies which key produced
    or is being asked to check a signature, without exposing or narrowing
    the key itself. Two different keys collide here only as often as sha256
    does, and the fingerprint cannot be inverted back into the key."""
    return short_id(hashlib.sha256(key).hexdigest())


def _mac(seal_digest: str, key: bytes) -> str:
    return hmac.new(key, seal_digest.encode("ascii"), hashlib.sha256).hexdigest()


def sign_report(report: dict[str, Any], key: bytes, *, source: str = "report") -> dict[str, Any]:
    """Sign a report's own seal.

    Refuses an unsealed or tampered report first — the same discipline
    `plumbline baseline` applies before distilling a baseline record:
    attesting to a report whose body does not match its own seal would sign
    bytes nobody actually verified, which is worse than not signing at all.
    """
    seal_digest = verify_report(report, source=source)
    return {
        "format": SIGNATURE_FORMAT,
        "algorithm": ALGORITHM,
        "seal_sha256": seal_digest,
        "key_id": key_id(key),
        "signature": _mac(seal_digest, key),
    }


def write_signature(signature: dict[str, Any], report_path: Path) -> Path:
    """Write a detached signature next to a report, as `report.sig`."""
    out = Path(report_path).parent / SIGNATURE_FILENAME
    with open(out, "w", encoding="utf-8") as f:
        json.dump(signature, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return out


def read_signature(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SigningError(f"unreadable signature file {path}: {e}") from e
    if not isinstance(data, dict):
        raise SigningError(f"{path} is not a Plumbline signature file")
    return data


def verify_signature(report: dict[str, Any], key: bytes, signature: dict[str, Any], *,
                     source: str = "report",
                     signature_source: str = SIGNATURE_FILENAME) -> str:
    """Recompute the report's seal, then check a detached signature against
    it and this key.

    Returns the key id that verified, so a caller can print which key
    attested to this report without ever printing the key itself.
    """
    if signature.get("format") != SIGNATURE_FORMAT:
        raise SigningError(
            f"{signature_source} is not a Plumbline signature file "
            f"(format {signature.get('format')!r})"
        )
    if signature.get("algorithm") != ALGORITHM:
        raise SigningError(
            f"{signature_source} names algorithm {signature.get('algorithm')!r}; "
            f"this build only checks {ALGORITHM!r}"
        )
    # The seal check is the same one `plumbline verify` runs on its own — a
    # signature over a report that does not match its own seal would attest
    # to nothing, so that refusal takes priority over a signature mismatch.
    seal_digest = verify_report(report, source=source)
    recorded_seal = signature.get("seal_sha256")
    if recorded_seal != seal_digest:
        raise SignatureMismatchError(
            f"{signature_source} signs seal {str(recorded_seal)[:12]}, but "
            f"{source} currently seals to {seal_digest[:12]}. Either this "
            f"is the signature for a different report, or the report was "
            f"re-run since it was signed."
        )
    expected = _mac(seal_digest, key)
    recorded_sig = signature.get("signature", "")
    if not isinstance(recorded_sig, str) or not hmac.compare_digest(expected, recorded_sig):
        raise SignatureMismatchError(
            f"{signature_source} does not verify against the key at hand: "
            f"either it was signed with a different key, or it was edited "
            f"after signing. This key's id is {key_id(key)}; the signature "
            f"names key id {signature.get('key_id')!r}."
        )
    return str(signature.get("key_id", ""))
