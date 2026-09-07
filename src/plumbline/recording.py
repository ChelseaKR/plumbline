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
    # The ceiling counts *turns*, because turns are what gets sent. A
    # question set of eighty items where twenty are three-turn conversations
    # is a hundred and twenty requests, and a ceiling that could only see the
    # eighty would let forty of them past a bound somebody set deliberately.
    turns_total = sum(1 + len(item.turns) for item in questions.items)
    max_items = getattr(adapter, "max_items", None)
    if max_items is not None and turns_total > max_items:
        multi = sum(1 for item in questions.items if item.turns)
        raise RecordingError(
            f"the question set has {len(questions.items)} items which come to "
            f"{turns_total} turn(s)"
            + (f" ({multi} of them multi-turn)" if multi else "")
            + f" and the adapter's max_items bound is {max_items}; raise it "
              f"deliberately if you mean to send that many requests"
        )

    # A multi-turn item and an adapter that was never told how a follow-up
    # turn reaches the target is a configuration error, not a single-turn
    # fallback. Recording the opener's answer under an item that declares
    # three turns produces a bundle whose `conversational_integrity` result is
    # entirely UNVERIFIABLE — a suite reporting it could not see anything,
    # about a recording that could have seen everything, with nothing saying
    # the recorder simply did not ask. Refused before the first request, so
    # the answer is "fix the config", not "look at what you already spent".
    conversation = getattr(adapter, "conversation", None)
    multi_turn = [item.id for item in questions.items if item.turns]
    if multi_turn and conversation is None:
        shown = ", ".join(multi_turn[:3]) + ("…" if len(multi_turn) > 3 else "")
        raise RecordingError(
            f"{len(multi_turn)} item(s) in this question set declare follow-up "
            f"turns ({shown}) and the [adapter] table has no "
            f"[adapter.conversation] saying how a follow-up turn reaches this "
            f"target. Recording them one turn deep would file the opener's "
            f"answer under a multi-turn item, and `conversational_integrity` "
            f"would report every one of them as unverifiable rather than as "
            f"never asked."
        )

    # Before anything is prepared, and long before a socket opens: a draft
    # item's prompt is blank, so recording against one would ask the live
    # target nothing and file the answer it got back under a question that
    # was never put.
    bundle_mod.refuse_drafts(questions, "recorded against")

    out_dir = _prepare_out_dir(out_dir, questions.path, overwrite=overwrite)
    on_error = getattr(adapter, "on_error", "abort")

    responses: list[dict[str, Any]] = []
    empty: list[dict[str, Any]] = []
    conversations = 0
    for item in questions.items:
        turns: list[str] | None = None
        try:
            if item.turns:
                turns = adapter.converse(item)
                _check_turns(item, turns)
                text = turns[-1]
                conversations += 1
            else:
                text = adapter.respond(item)
        except AdapterError as e:
            if on_error != "record_empty":
                raise
            # An empty answer is not a quiet skip: `smoke` has a floor of 1.00
            # and fails on it, and the failure is named in the manifest.
            #
            # A part-recorded conversation is dropped entirely rather than
            # padded out with empties: `turn_responses` must be 1:1 with the
            # declared turns, and a list of blanks would be graded as turns
            # where the target said nothing rather than turns nobody asked.
            # The item lands as an empty single-turn response, which `smoke`
            # fails on and `conversational_integrity` reports unverifiable.
            text = ""
            turns = None
            empty.append({"id": item.id, "error": str(e)})
        entry: dict[str, Any] = {"id": item.id, "response": text}
        if turns is not None:
            entry["turn_responses"] = turns
        responses.append(entry)
        if progress is not None:
            progress(item.id, text)

    _write_bundle(out_dir, questions, responses)
    manifest = _build_manifest(questions, adapter, responses, empty,
                               conversations=conversations,
                               turns_total=turns_total,
                               synthetic=synthetic, note=note)
    _write_json(out_dir / bundle_mod.MANIFEST_FILENAME, manifest)
    checksums = bundle_mod.seal(out_dir)

    return RecordingResult(
        out_dir=out_dir, manifest=manifest,
        dataset_sha256=checksums["bundle_sha256"],
        recorded=len(responses), empty=empty,
    )


def _check_turns(item: bundle_mod.Item, turns: object) -> None:
    """An adapter's conversation must be 1:1 with the item's declared turns.

    `bundle.py` refuses a `turn_responses` list of the wrong length when it
    loads the recording, so a mismatch would already be caught — but it would
    be caught *after* the recording was made and sealed, as a bundle that
    cannot be read, with the target already asked. Checking it here names the
    adapter while the recording is still in progress.
    """
    expected = 1 + len(item.turns)
    if (not isinstance(turns, list)
            or not all(isinstance(t, str) for t in turns)):
        raise AdapterError(
            f"item '{item.id}': the adapter returned "
            f"{type(turns).__name__}, not one answer string per turn")
    if len(turns) != expected:
        raise AdapterError(
            f"item '{item.id}' declares {expected} user turn(s) and the "
            f"adapter returned {len(turns)} answer(s); which answer belongs "
            f"to which turn would be a guess"
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
                    conversations: int, turns_total: int,
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
            # Turns, alongside items, because they are what was actually
            # asked: a reader checking a recording against a rate limit or an
            # operator's agreed volume needs the number of requests, and an
            # item count silently understates it for every conversation.
            "turns": turns_total,
        },
        "responses_recorded": len(responses),
        "conversations_recorded": conversations,
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
