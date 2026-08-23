"""Recording: turn a question set into an evidence bundle by asking a target.

This is the only place a live system's answers enter Plumbline, and it is
deliberately a separate step from grading them. Recording is a thing that
happened at a moment, against a system that can change underneath you;
grading is a pure function of committed bytes. Keeping them apart is what lets
the gate stay offline, deterministic and byte-reproducible while still being
pointed at something real.

What comes out is an ordinary evidence bundle — sealed, hashable, auditable by
exactly the same command as a hand-written one — with a `recording` block in
its manifest saying where the answers came from.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from collections.abc import Callable
from typing import Any

from . import bundle as bundle_mod
from .adapters import Adapter, AdapterError
from .errors import OutboundError

RESPONSES_FILENAME = "responses.jsonl"
RECORDING_MODE_LIVE = "live"


class RecordingError(OutboundError):
    """The recording could not be made or written (exit 4)."""


@dataclass
class RecordingResult:
    out_dir: Path
    manifest: dict[str, Any]
    dataset_sha256: str
    recorded: int
    empty: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dataset_id(self) -> str:
        return self.dataset_sha256[:12]


def _timestamp() -> str:
    """UTC, to the second.

    Reports carry no timestamps, because a report must be a pure function of
    its inputs. A recording is the opposite kind of object: the same target
    asked the same question tomorrow may answer differently, so *when* is part
    of what the evidence means. Putting the timestamp in the manifest — inside
    the hash, fixed at recording time — keeps both properties: the evidence is
    dated, and every later audit of it is still byte-reproducible.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _prepare_out_dir(out_dir: Path, questions_dir: Path, *, overwrite: bool) -> Path:
    out_dir = Path(out_dir).resolve()
    if out_dir == Path(questions_dir).resolve():
        raise RecordingError(
            f"refusing to record over the question set at {out_dir}: a "
            f"recording writes a new bundle, so that what was asked and what "
            f"answered are both still on disk"
        )
    if out_dir.exists():
        if not out_dir.is_dir():
            raise RecordingError(f"output path is not a directory: {out_dir}")
        if any(out_dir.iterdir()) and not overwrite:
            raise RecordingError(
                f"{out_dir} already has files in it; pass --overwrite to "
                f"replace that recording (its dataset hash will change, which "
                f"is the trace)"
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def record(*, questions: bundle_mod.Bundle, adapter: Adapter, out_dir: Path,
           overwrite: bool = False, synthetic: bool = False,
           note: str | None = None,
           progress: Callable[[str, str], None] | None = None) -> RecordingResult:
    """Ask the target every item in the question set and seal the result."""
    max_items = getattr(adapter, "max_items", None)
    if max_items is not None and len(questions.items) > max_items:
        raise RecordingError(
            f"the question set has {len(questions.items)} items and the "
            f"adapter's max_items bound is {max_items}; raise it deliberately "
            f"if you mean to send that many requests"
        )

    out_dir = _prepare_out_dir(out_dir, questions.path, overwrite=overwrite)
    on_error = getattr(adapter, "on_error", "abort")

    responses: list[dict[str, Any]] = []
    empty: list[dict[str, Any]] = []
    for item in questions.items:
        try:
            text = adapter.respond(item)
        except AdapterError as e:
            if on_error != "record_empty":
                raise
            # An empty answer is not a quiet skip: `smoke` has a floor of 1.00
            # and fails on it, and the failure is named in the manifest.
            text = ""
            empty.append({"id": item.id, "error": str(e)})
        responses.append({"id": item.id, "response": text})
        if progress is not None:
            progress(item.id, text)

    _write_bundle(out_dir, questions, responses)
    manifest = _build_manifest(questions, adapter, responses, empty,
                               synthetic=synthetic, note=note)
    _write_json(out_dir / bundle_mod.MANIFEST_FILENAME, manifest)
    checksums = bundle_mod.seal(out_dir)

    return RecordingResult(
        out_dir=out_dir, manifest=manifest,
        dataset_sha256=checksums["bundle_sha256"],
        recorded=len(responses), empty=empty,
    )


def _write_bundle(out_dir: Path, questions: bundle_mod.Bundle,
                  responses: list[dict[str, Any]]) -> None:
    """Copy the question set's files across, then write the responses.

    The manifest is written separately (it gains a `recording` block) and the
    checksum file is regenerated rather than copied. Any old responses file is
    left behind: this bundle's answers are the ones just recorded.
    """
    old_responses = questions.manifest.get("files", {}).get("responses")
    skip = {bundle_mod.CHECKSUMS_FILENAME, bundle_mod.MANIFEST_FILENAME,
            RESPONSES_FILENAME}
    if old_responses:
        skip.add(old_responses)
    for path in sorted(questions.path.iterdir()):
        if path.is_file() and path.name not in skip:
            shutil.copyfile(path, out_dir / path.name)
    with open(out_dir / RESPONSES_FILENAME, "w", encoding="utf-8") as f:
        for entry in responses:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _build_manifest(questions: bundle_mod.Bundle, adapter: Adapter,
                    responses: list[dict[str, Any]], empty: list[dict[str, Any]], *,
                    synthetic: bool, note: str | None) -> dict[str, Any]:
    manifest = dict(questions.manifest)
    files = {k: v for k, v in questions.manifest.get("files", {}).items()}
    files["responses"] = RESPONSES_FILENAME
    manifest["files"] = files

    # Whether the evidence is synthetic is a claim about the *target*, and
    # only the person running the recorder knows. Default to the honest
    # answer for a live system.
    manifest["synthetic"] = bool(synthetic)
    description = str(manifest.get("description", "")).strip()
    manifest["description"] = (
        f"{description} Responses recorded from a live target by the "
        f"Plumbline {adapter.kind} adapter.").strip()

    recording = {
        "mode": RECORDING_MODE_LIVE,
        "recorded_at": _timestamp(),
        "harness_version": _harness_version(),
        "adapter": adapter.describe(),
        "questions": {
            "name": questions.name,
            "version": questions.manifest.get("version"),
            "sha256": questions.dataset_sha256,
            "items": len(questions.items),
        },
        "responses_recorded": len(responses),
        "responses_recorded_empty": empty,
    }
    if note:
        recording["note"] = note
    manifest["recording"] = recording
    return manifest


def _harness_version() -> str:
    from . import __version__
    return __version__


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
