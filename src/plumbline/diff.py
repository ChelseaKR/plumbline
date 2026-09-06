"""What changed between two evidence bundles.

When the dataset hash moves, the baseline comparison refuses to compare the
scores and names the two hashes. That refusal is correct — the evidence is not
the same evidence, so the numbers are not the same measurement — and until now
it was also where the reader was left. "The dataset changed" is true and it is
not an answer to "what changed".

This module answers that, and it answers it from the sealed bytes only. Both
bundles are verified before a single field is compared, for exactly the reason
scoring is: a diff computed over unverified evidence would be a description of
files nobody vouched for, presented with the authority of one that was checked.
A missing or mismatched manifest is an integrity refusal (exit 3), not a diff
with a caveat.

The comparison is structural rather than textual. Two bundles that write the
same item with different key order, or the same fee as `$125` and `$125.00`,
have not changed; a JSON-line diff would say they had. What is reported is
per-item, per-field, and — for responses, the one field whose text is prose —
whether the *numbers* moved, because a changed number in a recorded answer is
the finding that made this worth writing. The tamper drill plants one.

Ordering is deterministic (sorted by id, then by field name) so that a diff is
diffable and a CI job can compare two of them.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from .bundle import Bundle, load_questions
from .judges import extract_numbers, normalize

DIFF_FORMAT = "plumbline-bundle-diff"
FORMAT_VERSION = 1

#: Item fields compared one by one. `id` is the key, so it is not a field that
#: can change; everything else the dataclass declares is compared, which means
#: a field added to `Item` is compared here without anyone remembering to add
#: it. `test_diff.py` asserts that property rather than trusting it.
_ITEM_KEY = "id"

#: Manifest keys whose value is a hash or a timestamp of the bundle's own
#: making rather than a statement about its contents. They are reported, but
#: under `provenance` rather than as content changes, because "the bundle was
#: re-sealed" and "the questions changed" are different findings.
_PROVENANCE_KEYS = ("recording", "created_at", "sealed_at")


def _fields(obj: Any, key: str) -> dict[str, Any]:
    return {f.name: getattr(obj, f.name)
            for f in dataclasses.fields(obj) if f.name != key}


def _field_changes(left: Any, right: Any, key: str) -> list[dict[str, Any]]:
    """Field-by-field difference between two records of the same type."""
    a, b = _fields(left, key), _fields(right, key)
    return [{"field": name, "from": a[name], "to": b[name]}
            for name in sorted(a) if a[name] != b[name]]


def _keyed(records: list[Any]) -> dict[str, Any]:
    return {r.id: r for r in records}


def _compare_records(
    left: dict[str, Any], right: dict[str, Any], key: str
) -> dict[str, Any]:
    added = sorted(set(right) - set(left))
    removed = sorted(set(left) - set(right))
    changed = []
    for ident in sorted(set(left) & set(right)):
        fields = _field_changes(left[ident], right[ident], key)
        if fields:
            changed.append({"id": ident, "fields": fields})
    return {"added": added, "removed": removed, "changed": changed}


def _response_change(before: str, after: str) -> dict[str, Any]:
    """What moved in one recorded answer.

    `normalize` is the harness's own normalisation — the one the judges score
    through — so "text unchanged" here means unchanged in the only sense any
    suite would have noticed. A response that differs only in capitalisation or
    punctuation is reported as a formatting change and not as a new answer.

    The numbers are extracted with `extract_numbers`, the same canonicalisation
    the load-bearing-fact check uses, so `$125.00` becoming `$125` is not a
    changed number and `850` becoming `900` is.
    """
    before_numbers = sorted(set(extract_numbers(before)))
    after_numbers = sorted(set(extract_numbers(after)))
    return {
        "text_changed": normalize(before) != normalize(after),
        "numbers_added": [n for n in after_numbers if n not in before_numbers],
        "numbers_removed": [n for n in before_numbers if n not in after_numbers],
        "from": before,
        "to": after,
    }


def _compare_responses(left: Bundle, right: Bundle) -> dict[str, Any]:
    a, b = left.responses, right.responses
    changed = []
    for ident in sorted(set(a) & set(b)):
        if a[ident] != b[ident]:
            entry = {"id": ident}
            entry.update(_response_change(a[ident], b[ident]))
            changed.append(entry)
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": changed,
    }


def _compare_mapping(a: dict[str, Any], b: dict[str, Any],
                     keys: list[str]) -> list[dict[str, Any]]:
    out = []
    for key in sorted(keys):
        before, after = a.get(key), b.get(key)
        if before != after:
            out.append({"key": key, "from": before, "to": after})
    return out


def _compare_manifest(left: Bundle, right: Bundle) -> dict[str, Any]:
    a, b = left.manifest, right.manifest
    content_keys = [k for k in set(a) | set(b) if k not in _PROVENANCE_KEYS]
    provenance_keys = [k for k in set(a) | set(b) if k in _PROVENANCE_KEYS]
    return {
        "changed": _compare_mapping(a, b, content_keys),
        "provenance": _compare_mapping(a, b, provenance_keys),
    }


def _side(bundle: Bundle) -> dict[str, Any]:
    return {
        "path": str(bundle.path),
        "name": bundle.name,
        "dataset_id": bundle.dataset_id,
        "dataset_sha256": bundle.dataset_sha256,
        "items": len(bundle.items),
        "responses": len(bundle.responses),
    }


def _any_change(diff: dict[str, Any]) -> bool:
    for section in ("items", "responses", "sources"):
        block = diff[section]
        if block["added"] or block["removed"] or block["changed"]:
            return True
    if diff["manifest"]["changed"] or diff["manifest"]["provenance"]:
        return True
    return bool(diff["dataset_changed"])


def diff_bundles(left_dir: Path, right_dir: Path) -> dict[str, Any]:
    """Compare two bundles, after verifying both.

    `load_questions` rather than `load`: a question set is a legitimate bundle
    with no responses yet, and "what changed between the question set I sent
    out and the one I got back recordings for" is a question worth being able
    to ask. Integrity is enforced identically either way — `load_questions`
    verifies every checksum before it parses anything, and raises
    `IntegrityError` when it cannot.
    """
    left = load_questions(Path(left_dir))
    right = load_questions(Path(right_dir))
    diff: dict[str, Any] = {
        "format": DIFF_FORMAT,
        "format_version": FORMAT_VERSION,
        "left": _side(left),
        "right": _side(right),
        "dataset_changed": left.dataset_sha256 != right.dataset_sha256,
        "items": _compare_records(_keyed(left.items), _keyed(right.items), _ITEM_KEY),
        "responses": _compare_responses(left, right),
        "sources": _compare_records(left.sources, right.sources, _ITEM_KEY),
        "manifest": _compare_manifest(left, right),
    }
    diff["changed"] = _any_change(diff)
    return diff


def _short(value: Any, limit: int = 120) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False,
                                                           sort_keys=True)
    text = text.replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_for_terminal(diff: dict[str, Any]) -> list[str]:
    """The lines a reader gets. Every difference the structure records has to
    reach here: a section that is counted in `changed` and rendered nowhere is
    a change reported as nothing having happened, which is the failure this
    whole project is about."""
    left, right = diff["left"], diff["right"]
    lines = [
        f"diff: {left['name']} ({left['dataset_id']}) -> "
        f"{right['name']} ({right['dataset_id']})",
    ]
    if not diff["changed"]:
        lines.append("  no difference: the two bundles are the same evidence")
        return lines

    if diff["dataset_changed"]:
        lines.append(
            f"  dataset hash: {left['dataset_sha256']} -> "
            f"{right['dataset_sha256']}")

    for section, noun in (("items", "item"), ("sources", "source")):
        block = diff[section]
        for ident in block["removed"]:
            lines.append(f"  {noun} removed: {ident}")
        for ident in block["added"]:
            lines.append(f"  {noun} added:   {ident}")
        for entry in block["changed"]:
            for field in entry["fields"]:
                lines.append(
                    f"  {noun} changed: {entry['id']}.{field['field']}: "
                    f"{_short(field['from'])} -> {_short(field['to'])}")

    responses = diff["responses"]
    for ident in responses["removed"]:
        lines.append(f"  response removed: {ident}")
    for ident in responses["added"]:
        lines.append(f"  response added:   {ident}")
    for entry in responses["changed"]:
        moved = entry["numbers_removed"], entry["numbers_added"]
        if moved[0] or moved[1]:
            lines.append(
                f"  response changed: {entry['id']}: "
                f"{', '.join(moved[0]) or '(none)'} became "
                f"{', '.join(moved[1]) or '(none)'}")
        elif entry["text_changed"]:
            lines.append(
                f"  response changed: {entry['id']}: wording changed, no "
                f"number moved")
        else:
            # Normalisation-only: neither a judge nor a reader would see a
            # different answer, and saying "changed" without saying that would
            # send someone hunting for a difference that is not there.
            lines.append(
                f"  response changed: {entry['id']}: formatting only "
                f"(punctuation, case or whitespace)")

    for entry in diff["manifest"]["changed"]:
        lines.append(
            f"  manifest: {entry['key']}: {_short(entry['from'])} -> "
            f"{_short(entry['to'])}")
    for entry in diff["manifest"]["provenance"]:
        lines.append(
            f"  provenance: {entry['key']}: {_short(entry['from'])} -> "
            f"{_short(entry['to'])}")
    return lines
