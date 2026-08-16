"""Evidence bundle: loading, integrity verification, and sealing.

A bundle is a directory holding dataset items, recorded target responses, and
a checksum manifest (see DESIGN.md, "Evidence bundle format"). Integrity is
verified BEFORE anything is parsed for scoring; a mismatch or a missing
checksum manifest raises IntegrityError, which the CLI maps to the distinct
integrity exit code. There is no path that scores unverified evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .hashing import bundle_digest, sha256_file, short_id

CHECKSUMS_FILENAME = "checksums.json"
MANIFEST_FILENAME = "manifest.json"

BUNDLE_FORMAT = "plumbline-bundle"
CHECKSUMS_FORMAT = "plumbline-checksums"
FORMAT_VERSION = 1

BEHAVIOR_CLASSES = ("answer", "refuse")
REVIEW_STATUSES = ("sme_reviewed", "unreviewed")


class BundleError(Exception):
    """The bundle is malformed or unreadable (configuration error, exit 4)."""


class IntegrityError(Exception):
    """Checksums are missing or do not match (integrity refusal, exit 3)."""


@dataclass
class Source:
    """One passage the target could have grounded an answer in."""
    id: str
    text: str
    title: str | None = None
    url: str | None = None


@dataclass
class Item:
    id: str
    lang: str
    behavior: str
    prompt: str
    expected: str | None = None
    load_bearing: bool = False
    fact_id: str | None = None
    group: str | None = None
    translation: dict | None = None
    sources: list[str] = field(default_factory=list)  # source ids retrieved for this item
    # Opt-in: the source ids that actually ANSWER this question, as opposed to
    # the ones that were merely retrieved. Only the `passage_attribution`
    # suite reads it, and an item that declares nothing is reported
    # UNVERIFIABLE there rather than passed.
    answering_sources: list[str] = field(default_factory=list)
    adversarial: bool = False  # this prompt is an attack probe
    forbidden: list[str] = field(default_factory=list)  # must not appear in the response


@dataclass
class Bundle:
    path: Path
    manifest: dict
    items: list[Item]
    responses: dict[str, str]  # item id -> recorded response text
    dataset_sha256: str
    sources: dict[str, Source] = field(default_factory=dict)

    def source(self, source_id: str) -> Source | None:
        return self.sources.get(source_id)

    def sources_for(self, item: Item) -> list[Source]:
        """The passages retrieved for one item, in declared order."""
        return [self.sources[sid] for sid in item.sources if sid in self.sources]

    def source_text_for(self, item: Item) -> str:
        return "\n".join(s.text for s in self.sources_for(item))

    def answering_sources_for(self, item: Item) -> list[Source]:
        """The passages the item declares as answering its question.

        Not necessarily a subset of the passages it had: an answering passage
        the target never retrieved is a retrieval failure, and the attribution
        suite names it as one instead of pretending it was on the desk.
        """
        return [self.sources[sid] for sid in item.answering_sources
                if sid in self.sources]

    def distractor_sources_for(self, item: Item) -> list[Source]:
        """The passages the item had that it does *not* declare as answering
        the question: what a wrong-paragraph answer would have come from."""
        return [self.sources[sid] for sid in item.sources
                if sid in self.sources and sid not in item.answering_sources]

    @property
    def dataset_id(self) -> str:
        return short_id(self.dataset_sha256)

    @property
    def name(self) -> str:
        return self.manifest.get("name", self.path.name)

    def response_for(self, item_id: str) -> str | None:
        return self.responses.get(item_id)

    def unreviewed_translation_warnings(self) -> list[str]:
        """One warning line per unreviewed translated item. Visible on every
        run; never fatal, never suppressed."""
        warnings = []
        for item in self.items:
            t = item.translation
            if t and t.get("review") == "unreviewed":
                warnings.append(
                    f"item {item.id} ({item.lang}): translation of "
                    f"{t.get('of', '?')} lacks subject-matter-expert review"
                )
        return warnings


def hashed_files(bundle_dir: Path) -> list[Path]:
    """Every regular file in the bundle except the checksum manifest itself."""
    return sorted(
        p for p in bundle_dir.iterdir()
        if p.is_file() and p.name != CHECKSUMS_FILENAME
    )


def compute_checksums(bundle_dir: Path) -> dict:
    files = {p.name: sha256_file(p) for p in hashed_files(bundle_dir)}
    return {
        "format": CHECKSUMS_FORMAT,
        "format_version": FORMAT_VERSION,
        "algorithm": "sha256",
        "files": files,
        "bundle_sha256": bundle_digest(files),
    }


def seal(bundle_dir: Path) -> dict:
    """(Re)generate checksums.json. The only legitimate way to change
    evidence; it always leaves a trace, because the bundle hash changes."""
    bundle_dir = Path(bundle_dir)
    if not bundle_dir.is_dir():
        raise BundleError(f"not a directory: {bundle_dir}")
    checksums = compute_checksums(bundle_dir)
    out = bundle_dir / CHECKSUMS_FILENAME
    with open(out, "w", encoding="utf-8") as f:
        json.dump(checksums, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return checksums


def verify_integrity(bundle_dir: Path) -> str:
    """Verify every recorded checksum. Returns the bundle hash on success.

    Raises IntegrityError on: missing checksums.json, malformed checksums.json,
    a file listed but absent, a file present but unlisted, or any digest
    mismatch. Unverifiable evidence fails closed.
    """
    bundle_dir = Path(bundle_dir)
    checksums_path = bundle_dir / CHECKSUMS_FILENAME
    if not checksums_path.is_file():
        raise IntegrityError(
            f"no {CHECKSUMS_FILENAME} in {bundle_dir}: evidence cannot be "
            f"verified (run `plumbline seal` on a bundle you trust)"
        )
    try:
        with open(checksums_path, encoding="utf-8") as f:
            recorded = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise IntegrityError(f"unreadable {CHECKSUMS_FILENAME}: {e}") from e

    if recorded.get("format") != CHECKSUMS_FORMAT or recorded.get("algorithm") != "sha256":
        raise IntegrityError(f"{CHECKSUMS_FILENAME} is not a recognized checksum manifest")

    recorded_files: dict = recorded.get("files", {})
    actual = {p.name: sha256_file(p) for p in hashed_files(bundle_dir)}

    problems = []
    for name in sorted(set(recorded_files) | set(actual)):
        if name not in actual:
            problems.append(f"listed but missing: {name}")
        elif name not in recorded_files:
            problems.append(f"present but not listed: {name}")
        elif recorded_files[name] != actual[name]:
            problems.append(f"content mismatch: {name}")
    expected_bundle = bundle_digest(recorded_files)
    if recorded.get("bundle_sha256") != expected_bundle:
        problems.append("bundle_sha256 does not match the per-file digests")

    if problems:
        raise IntegrityError(
            "evidence bundle failed integrity verification: " + "; ".join(problems)
        )
    return recorded["bundle_sha256"]


def _declared(bundle_dir: Path, filename: str, role: str) -> Path:
    """A file the manifest declares must actually be there. Named rather than
    left to raise an unhandled FileNotFoundError deeper in."""
    path = bundle_dir / filename
    if not path.is_file():
        raise BundleError(
            f"{MANIFEST_FILENAME} declares files.{role} = '{filename}', which "
            f"is not in the bundle"
        )
    return path


def _parse_items(path: Path) -> list[Item]:
    items: list[Item] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                raise BundleError(f"{path.name}:{lineno}: invalid JSON: {e}") from e
            for req in ("id", "lang", "behavior", "prompt"):
                if req not in raw:
                    raise BundleError(f"{path.name}:{lineno}: missing required field '{req}'")
            if raw["behavior"] not in BEHAVIOR_CLASSES:
                raise BundleError(
                    f"{path.name}:{lineno}: behavior must be one of {BEHAVIOR_CLASSES}"
                )
            if raw["id"] in seen:
                raise BundleError(f"{path.name}:{lineno}: duplicate item id '{raw['id']}'")
            if raw["behavior"] == "answer" and not raw.get("expected"):
                raise BundleError(
                    f"{path.name}:{lineno}: answer item '{raw['id']}' has no expected answer"
                )
            item_sources = raw.get("sources", [])
            if not isinstance(item_sources, list) or not all(
                    isinstance(s, str) for s in item_sources):
                raise BundleError(
                    f"{path.name}:{lineno}: 'sources' must be a list of "
                    f"source ids"
                )
            answering = raw.get("answering_sources")
            if answering is not None:
                if not isinstance(answering, list) or not all(
                        isinstance(s, str) for s in answering):
                    raise BundleError(
                        f"{path.name}:{lineno}: 'answering_sources' must be a "
                        f"list of source ids"
                    )
                if not answering:
                    raise BundleError(
                        f"{path.name}:{lineno}: item '{raw['id']}' declares an "
                        f"empty 'answering_sources'. An answer item with no "
                        f"passage that answers it is a contradiction; omit the "
                        f"field and the attribution suite reports the item as "
                        f"unverifiable instead"
                    )
                if raw["behavior"] != "answer":
                    raise BundleError(
                        f"{path.name}:{lineno}: item '{raw['id']}' expects a "
                        f"refusal and declares 'answering_sources'. Nothing "
                        f"answers a question that should not be answered"
                    )
            forbidden = raw.get("forbidden", [])
            if not isinstance(forbidden, list) or not all(
                    isinstance(s, str) for s in forbidden):
                raise BundleError(
                    f"{path.name}:{lineno}: 'forbidden' must be a list of "
                    f"strings that must not appear in the response"
                )
            t = raw.get("translation")
            if t is not None and t.get("review") not in REVIEW_STATUSES:
                raise BundleError(
                    f"{path.name}:{lineno}: translation.review must be one of {REVIEW_STATUSES}"
                )
            seen.add(raw["id"])
            items.append(Item(
                id=raw["id"],
                lang=raw["lang"],
                behavior=raw["behavior"],
                prompt=raw["prompt"],
                expected=raw.get("expected"),
                load_bearing=bool(raw.get("load_bearing", False)),
                fact_id=raw.get("fact_id"),
                group=raw.get("group"),
                translation=t,
                sources=item_sources,
                answering_sources=list(answering or []),
                adversarial=bool(raw.get("adversarial", False)),
                forbidden=forbidden,
            ))
    if not items:
        raise BundleError(f"{path.name}: no items")
    return items


def _parse_sources(path: Path) -> dict[str, Source]:
    sources: dict[str, Source] = {}
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                raise BundleError(f"{path.name}:{lineno}: invalid JSON: {e}") from e
            for req in ("id", "text"):
                if not raw.get(req):
                    raise BundleError(f"{path.name}:{lineno}: missing '{req}'")
            if raw["id"] in sources:
                raise BundleError(f"{path.name}:{lineno}: duplicate source id "
                                  f"'{raw['id']}'")
            sources[raw["id"]] = Source(
                id=raw["id"], text=raw["text"],
                title=raw.get("title"), url=raw.get("url"),
            )
    return sources


def _parse_responses(path: Path, item_ids: set[str]) -> dict[str, str]:
    responses: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                raise BundleError(f"{path.name}:{lineno}: invalid JSON: {e}") from e
            if "id" not in raw or "response" not in raw:
                raise BundleError(f"{path.name}:{lineno}: needs 'id' and 'response'")
            if raw["id"] not in item_ids:
                raise BundleError(f"{path.name}:{lineno}: response for unknown item '{raw['id']}'")
            if raw["id"] in responses:
                raise BundleError(f"{path.name}:{lineno}: duplicate response for '{raw['id']}'")
            responses[raw["id"]] = raw["response"]
    return responses


def load(bundle_dir: Path) -> Bundle:
    """Verify integrity, then parse. Integrity always comes first: nothing is
    parsed for scoring from a bundle that failed verification."""
    return _load(bundle_dir, require_responses=True)


def load_questions(bundle_dir: Path) -> Bundle:
    """Load a bundle that may not have any responses yet.

    A *question set* is an evidence bundle without the evidence: items, an
    optional source corpus, an optional interface snapshot, sealed like any
    other bundle. It is what a live-target adapter records against, and it is
    verified before a single request goes out — recording against unverified
    questions would produce evidence nobody could defend.

    The scoring path never uses this loader: an audit always requires
    responses.
    """
    return _load(bundle_dir, require_responses=False)


def _load(bundle_dir: Path, *, require_responses: bool) -> Bundle:
    bundle_dir = Path(bundle_dir)
    if not bundle_dir.is_dir():
        raise BundleError(f"bundle path is not a directory: {bundle_dir}")

    dataset_sha256 = verify_integrity(bundle_dir)

    manifest_path = bundle_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise BundleError(f"missing {MANIFEST_FILENAME}")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    if manifest.get("format") != BUNDLE_FORMAT:
        raise BundleError(f"{MANIFEST_FILENAME}: format is not '{BUNDLE_FORMAT}'")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise BundleError(
            f"{MANIFEST_FILENAME}: unsupported format_version "
            f"{manifest.get('format_version')!r} (supported: {FORMAT_VERSION})"
        )

    files = manifest.get("files", {})
    items_name = files.get("items")
    responses_name = files.get("responses")
    if not items_name:
        raise BundleError(f"{MANIFEST_FILENAME}: files.items is required")
    if require_responses and not responses_name:
        raise BundleError(
            f"{MANIFEST_FILENAME}: files.responses is required to score a "
            f"bundle (a bundle without responses is a question set: record "
            f"against it with `plumbline record`)"
        )

    items = _parse_items(_declared(bundle_dir, items_name, "items"))
    responses = (
        _parse_responses(_declared(bundle_dir, responses_name, "responses"),
                         {i.id for i in items})
        if responses_name else {}
    )

    sources_name = files.get("sources")
    sources = (_parse_sources(_declared(bundle_dir, sources_name, "sources"))
               if sources_name else {})

    # An item that points at a source which is not in the corpus would make
    # every grounding score meaningless, so it is a bundle error, not a
    # runtime surprise.
    for item in items:
        missing = [sid for sid in item.sources if sid not in sources]
        if missing:
            raise BundleError(
                f"item '{item.id}' cites source ids that are not in the "
                f"corpus: {', '.join(missing)}"
                + ("" if sources_name else
                   " (the manifest declares no files.sources)")
            )
        # An answering passage nobody can read is a declaration that cannot be
        # checked, and the suite would grade every answer against nothing.
        unresolved = [sid for sid in item.answering_sources if sid not in sources]
        if unresolved:
            raise BundleError(
                f"item '{item.id}' declares answering_sources that are not in "
                f"the corpus: {', '.join(unresolved)}"
                + ("" if sources_name else
                   " (the manifest declares no files.sources)")
            )

    return Bundle(
        path=bundle_dir,
        manifest=manifest,
        items=items,
        responses=responses,
        dataset_sha256=dataset_sha256,
        sources=sources,
    )
