"""Shared test fixtures: build small evidence bundles programmatically."""

from __future__ import annotations

import json
from pathlib import Path

from plumbline.bundle import seal


def write_bundle(
    root: Path,
    items: list[dict],
    responses: list[dict],
    *,
    name: str = "test-bundle",
    do_seal: bool = True,
) -> Path:
    bundle_dir = Path(root) / name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": "plumbline-bundle",
        "format_version": 1,
        "name": name,
        "version": "0.0.1",
        "synthetic": True,
        "description": "synthetic fixture for tests",
        "files": {"items": "items.jsonl", "responses": "responses.jsonl"},
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (bundle_dir / "items.jsonl").write_text(
        "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8"
    )
    (bundle_dir / "responses.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in responses), encoding="utf-8"
    )
    if do_seal:
        seal(bundle_dir)
    return bundle_dir


def answer_item(item_id: str, expected: str, **extra) -> dict:
    return {
        "id": item_id, "lang": "en", "behavior": "answer",
        "prompt": f"prompt for {item_id}", "expected": expected, **extra,
    }


def refuse_item(item_id: str, **extra) -> dict:
    return {
        "id": item_id, "lang": "en", "behavior": "refuse",
        "prompt": f"prompt for {item_id}", **extra,
    }


def response(item_id: str, text: str) -> dict:
    return {"id": item_id, "response": text}
