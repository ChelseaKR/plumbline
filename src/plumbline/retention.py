"""Recording retention and redaction: a lifecycle companion to `plumbline
record`, closing the gap the README's Data Governance row already names —
"no data card and no stated retention position for recordings, which the
`.gitignore` keeps out of the repository but does not otherwise govern."

`plumbline record` captures live-target transcripts against real question
sets, for a harness whose entire subject is government-facing chat. Those
transcripts are exactly the kind of artifact that can carry the personal
data `privacy.py` exists to screen for in the *target's* answers, sitting
unmanaged on whoever's disk ran the recording. This module reuses that exact
screen — `judges.LexicalJudge.pii_in`, the same primitive `privacy.py`
scores with — for a governance purpose instead of a grading one.

**What a clean screen means here is exactly what it means there.** Pattern
matching finds identifiers, not judgment calls: a clean pass after `retire`
means no shipped pattern matched any more, not that no personal data
remains. `docs/recordings-data-card.md` says this again, in the place a
reader looking for a retention policy would actually look first.

**Silence is never evidence, here either.** A recording nobody has looked at
past its own retention window is not a retention policy; it is the absence
of one, wearing a `.gitignore` entry. `plumbline retire` past that window
refuses outright when a flagged pattern is still present and redaction was
not requested — the same posture the gate takes on a suite that fails, not
a warning that can be scrolled past.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import bundle as bundle_mod
from .judges import LexicalJudge

REDACTION_PLACEHOLDER = "[REDACTED:{kind}]"


class RetentionError(Exception):
    """A recording is not eligible for retirement, or is past its retention
    window and still carries personal data without redaction being asked
    for (configuration error)."""


@dataclass
class RetentionResult:
    bundle_dir: Path
    recorded_at: str | None
    age_days: float
    max_age_days: int
    # item id -> [(pii kind, matched text), ...], as found BEFORE any
    # redaction this call performed.
    findings: dict[str, list[tuple[str, str]]]
    redacted_count: int


def _recording_block(bundle) -> dict:
    recording = bundle.manifest.get("recording")
    if not recording:
        raise RetentionError(
            f"{bundle.path} has no 'recording' block in its manifest, so it "
            f"is not evidence `plumbline record` produced. Retention only "
            f"governs recordings of a live target; a hand-written or "
            f"synthetic bundle has no recording date to retire it against."
        )
    return recording


def age_days(recording: dict, *, now: datetime | None = None) -> float:
    """Days since a recording was made, from the manifest's own
    `recording.recorded_at` — the one timestamp this harness writes down on
    purpose, and the only place an age like this can honestly come from."""
    recorded_at = recording.get("recorded_at")
    if not recorded_at:
        raise RetentionError(
            "recording block has no recorded_at timestamp; cannot compute "
            "its age")
    try:
        recorded = datetime.fromisoformat(recorded_at)
    except ValueError as e:
        raise RetentionError(
            f"unreadable recorded_at {recorded_at!r}: {e}") from e
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - recorded).total_seconds() / 86400.0


def screen(bundle) -> dict[str, list[tuple[str, str]]]:
    """Every personal-data pattern found in each recorded response.

    Reuses `LexicalJudge.pii_in` directly: this is `privacy.py`'s own check,
    run over the whole recorded response regardless of what the prompt or
    the item's sources already contained, because retention is about what
    this file holds, not about whether the target disclosed something new.
    """
    judge = LexicalJudge()
    findings: dict[str, list[tuple[str, str]]] = {}
    for item_id, text in bundle.responses.items():
        matches = judge.pii_in(text or "")
        if matches:
            findings[item_id] = matches
    return findings


def _redact_text(text: str, matches: list[tuple[str, str]]) -> str:
    # Longest match first, so a shorter match that happens to be a substring
    # of a longer one (a phone number's area code inside the full number, an
    # id embedded in a longer id) does not get replaced first and split the
    # longer placeholder in two.
    for kind, value in sorted(set(matches), key=lambda kv: -len(kv[1])):
        if value:
            text = text.replace(value, REDACTION_PLACEHOLDER.format(kind=kind))
    return text


def redact(bundle, findings: dict[str, list[tuple[str, str]]]) -> int:
    """Rewrite this bundle's responses.jsonl in place, replacing every
    matched span with a placeholder naming the kind of data it was, then
    reseal — the only legitimate way to change evidence, and it always
    leaves a trace, because the bundle hash changes.

    Returns how many responses were changed. A screen, not a guarantee: see
    this module's docstring.
    """
    if not findings:
        return 0
    responses_path = bundle.sealed(
        bundle.manifest["files"]["responses"], "responses")
    entries = []
    changed = 0
    with open(responses_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            item_id = entry.get("id")
            if item_id in findings:
                entry["response"] = _redact_text(
                    entry.get("response", ""), findings[item_id])
                changed += 1
            entries.append(entry)
    with open(responses_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    bundle_mod.seal(bundle.path)
    return changed


def retire(bundle_dir: Path, *, max_age_days: int, redact_now: bool = False,
          now: datetime | None = None) -> RetentionResult:
    """Screen a recorded bundle, and either report, redact, or refuse.

    - Findings within the retention window: reported, never fatal — the
      window has not been crossed yet.
    - Findings past the window, `redact_now` not set: refused. Silence
      about a retention policy is not a retention policy.
    - `redact_now` set: redacted and resealed regardless of age — early
      hygiene is always allowed, never required before the window closes.
    """
    bundle = bundle_mod.load(Path(bundle_dir))
    recording = _recording_block(bundle)
    age = age_days(recording, now=now)
    findings = screen(bundle)
    past_window = age > max_age_days

    redacted_count = 0
    if findings and redact_now:
        redacted_count = redact(bundle, findings)
    elif findings and past_window:
        ids = sorted(findings)
        shown = ", ".join(ids[:5]) + ("…" if len(ids) > 5 else "")
        raise RetentionError(
            f"{bundle_dir} was recorded {age:.1f} day(s) ago, past its "
            f"{max_age_days}-day retention window, and {len(findings)} "
            f"response(s) still carry a personal-data pattern this screen "
            f"catches ({shown}). Pass --redact to bring it into compliance, "
            f"or delete the recording; silence about a retention policy is "
            f"not a retention policy."
        )

    return RetentionResult(
        bundle_dir=Path(bundle_dir), recorded_at=recording.get("recorded_at"),
        age_days=age, max_age_days=max_age_days, findings=findings,
        redacted_count=redacted_count,
    )
