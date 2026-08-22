"""Evidence bundle: loading, integrity verification, and sealing.

A bundle is a directory holding dataset items, recorded target responses, and
a checksum manifest (see DESIGN.md, "Evidence bundle format"). Integrity is
verified BEFORE anything is parsed for scoring; a mismatch or a missing
checksum manifest raises IntegrityError, which the CLI maps to the distinct
integrity exit code. There is no path that scores unverified evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .hashing import bundle_digest, sha256_file, short_id

CHECKSUMS_FILENAME = "checksums.json"
MANIFEST_FILENAME = "manifest.json"

_SHA256_HEX_RE = re.compile(r"\A[0-9a-f]{64}\Z")

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
    # Opt-in: follow-up user turns after `prompt`, which is turn one. The full
    # conversation's user side is `[prompt] + turns`. Empty (the default) is
    # today's single-turn item, unchanged in every way that matters to a
    # suite that has never heard of `turns` — see `conversational_integrity.py`
    # and Bundle.turns_for/turn_responses_for, the only two places that read
    # this field.
    turns: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)  # must not appear in the response
    # Must not be *asserted*. The weaker of the two, and the one a consumer
    # needs when the correct answer is a denial: "the deadline is the 15th" has
    # to be sayable in the sentence "no, the deadline is not the 15th". A
    # string that must never appear in any grammatical role belongs in
    # `forbidden`, which is checked by substring and cannot be talked around.
    forbidden_claims: list[str] = field(default_factory=list)


@dataclass
class Bundle:
    path: Path
    manifest: dict
    items: list[Item]
    responses: dict[str, str]  # item id -> recorded response text
    dataset_sha256: str
    # item id -> one recorded response per user turn, in order, for the
    # opt-in items that declare `turns`. Independent of `responses` above,
    # which every existing suite that has never heard of multi-turn items
    # keeps reading exactly as it always did; the two ordinarily agree
    # because whatever recorded a conversation wrote both from it, but
    # nothing here requires it — see `_parse_responses`. Absent for a
    # single-turn item; present and >= 2 long for one that declares `turns`.
    turn_responses: dict[str, list[str]] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    # Bundle-relative path -> sha256, exactly as the verified manifest recorded
    # it. The definitive list of bytes this bundle vouches for; a suite that
    # wants to open something asks for it through `sealed`.
    covered: dict[str, str] = field(default_factory=dict)

    def sealed(self, filename: str, role: str) -> Path:
        """A path inside this bundle that a checksum covers, or a BundleError.

        Any code that opens a file from the bundle goes through here. Joining
        a manifest-supplied name onto the bundle directory does not: an
        absolute name escapes, `..` escapes, and a name in a subdirectory used
        to be readable without any checksum covering it at all.
        """
        return sealed_path(self.path, filename, role, self.covered)

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

    def turns_for(self, item: Item) -> list[str]:
        """The full conversation's user-side turns, in order: `prompt` is
        always turn one. A single-turn item (the default) returns a
        one-element list, so this is always safe to call."""
        return [item.prompt, *item.turns]

    def turn_responses_for(self, item_id: str) -> list[str] | None:
        """One recorded response per user turn, in order — or None for an
        item that was never recorded as multi-turn. Present only for items
        that declared `turns` AND were recorded with a matching
        `turn_responses` list; see `conversational_integrity.py`."""
        return self.turn_responses.get(item_id)

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


def check_hashable_name(name: str) -> str:
    """Refuse a bundle-relative path the combined bundle hash cannot represent
    unambiguously. Returns the name.

    `bundle_digest` serialises the manifest as one `"<name>=<64 hex>\\n"` line
    per file. A name containing a newline could therefore forge a line break
    and make one file serialise exactly like two, so two different sets of
    evidence would share a bundle hash. POSIX permits newlines in filenames,
    so this is a real construction and not a theoretical one; the digest stays
    injective only because such names are refused at both ends — when a bundle
    is sealed, and when a recorded manifest is read back.
    """
    if not isinstance(name, str) or not name:
        raise IntegrityError(
            f"{CHECKSUMS_FILENAME} lists a file name that is not a "
            f"non-empty string: {name!r}"
        )
    bad = [c for c in ("\n", "\r", "\x00") if c in name]
    if bad:
        raise IntegrityError(
            f"bundle contains a path whose name has a line break or NUL in "
            f"it ({name!r}). The combined bundle hash is line-oriented, so "
            f"such a name could make two different bundles hash identically. "
            f"Rename the file."
        )
    return name


def _walk(bundle_dir: Path):
    """Every regular file anywhere under the bundle, depth first.

    Symbolic links are refused outright, directories included. A link is a
    name that points somewhere else, and 'somewhere else' is not evidence this
    bundle sealed: the target can be swapped, can sit outside the bundle
    entirely, and need not even be a file. Refusing is the only answer that
    keeps 'the manifest vouches for every byte read' true.
    """
    stack = [Path(bundle_dir)]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir()):
            if entry.is_symlink():
                raise IntegrityError(
                    f"bundle contains a symbolic link "
                    f"({entry.relative_to(bundle_dir).as_posix()}). Evidence "
                    f"must be the bytes in the bundle, not a pointer at bytes "
                    f"somewhere else; replace the link with the file."
                )
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file():
                yield entry
            else:
                raise IntegrityError(
                    f"bundle contains something that is not a regular file "
                    f"({entry.relative_to(bundle_dir).as_posix()}); it cannot "
                    f"be hashed, so it cannot be evidence"
                )


def hashed_files(bundle_dir: Path) -> dict[str, Path]:
    """Every regular file in the bundle, at any depth, except the checksum
    manifest itself — keyed by its POSIX path relative to the bundle root.

    Recursive on purpose. Hashing only the top level would leave evidence in a
    subdirectory unsealed: it could be rewritten while the bundle hash, the
    integrity verdict and the run id all stayed identical, which is precisely
    the tamper this tool exists to make impossible.
    """
    bundle_dir = Path(bundle_dir)
    found: dict[str, Path] = {}
    for path in _walk(bundle_dir):
        name = path.relative_to(bundle_dir).as_posix()
        if name == CHECKSUMS_FILENAME:
            continue
        found[check_hashable_name(name)] = path
    return dict(sorted(found.items()))


def compute_checksums(bundle_dir: Path) -> dict:
    files = {name: sha256_file(p)
             for name, p in hashed_files(bundle_dir).items()}
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


def _verify(bundle_dir: Path) -> tuple[str, dict[str, str]]:
    """Verify every recorded checksum.

    Returns the bundle hash and the sealed map of bundle-relative path ->
    sha256, which is the definitive list of bytes this bundle vouches for.
    Nothing outside that map may be read.
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

    if not isinstance(recorded, dict):
        raise IntegrityError(f"{CHECKSUMS_FILENAME} is not a JSON object")
    if recorded.get("format") != CHECKSUMS_FORMAT or recorded.get("algorithm") != "sha256":
        raise IntegrityError(f"{CHECKSUMS_FILENAME} is not a recognized checksum manifest")

    recorded_files = recorded.get("files")
    if not isinstance(recorded_files, dict):
        raise IntegrityError(
            f"{CHECKSUMS_FILENAME} has no 'files' object, so it vouches for "
            f"nothing"
        )
    # A hand-written manifest is untrusted input like any other. Its names must
    # be ones the combined hash can represent unambiguously, and its digests
    # must be digests — otherwise a crafted manifest could make the recomputed
    # bundle hash agree with a set of files it does not describe.
    for name, digest in recorded_files.items():
        check_hashable_name(name)
        if not isinstance(digest, str) or not _SHA256_HEX_RE.match(digest):
            raise IntegrityError(
                f"{CHECKSUMS_FILENAME}: the entry for '{name}' is not a "
                f"lowercase sha256 hex digest"
            )
    recorded_bundle = recorded.get("bundle_sha256")
    if not isinstance(recorded_bundle, str) or not _SHA256_HEX_RE.match(recorded_bundle):
        raise IntegrityError(
            f"{CHECKSUMS_FILENAME}: bundle_sha256 is not a lowercase sha256 "
            f"hex digest"
        )

    actual = {name: sha256_file(p)
              for name, p in hashed_files(bundle_dir).items()}

    problems = []
    for name in sorted(set(recorded_files) | set(actual)):
        if name not in actual:
            problems.append(f"listed but missing: {name}")
        elif name not in recorded_files:
            problems.append(f"present but not listed: {name}")
        elif recorded_files[name] != actual[name]:
            problems.append(f"content mismatch: {name}")
    if recorded_bundle != bundle_digest(recorded_files):
        problems.append("bundle_sha256 does not match the per-file digests")

    if problems:
        raise IntegrityError(
            "evidence bundle failed integrity verification: " + "; ".join(problems)
        )
    return recorded_bundle, dict(recorded_files)


def verify_integrity(bundle_dir: Path) -> str:
    """Verify every recorded checksum. Returns the bundle hash on success.

    Raises IntegrityError on: missing checksums.json, malformed checksums.json,
    a file listed but absent, a file present but unlisted, a symbolic link
    anywhere in the tree, or any digest mismatch. Unverifiable evidence fails
    closed.
    """
    return _verify(bundle_dir)[0]


def sealed_path(bundle_dir: Path, filename: str, role: str,
                covered: dict[str, str]) -> Path:
    """Resolve a path the manifest declares, or refuse.

    Three things have to be true before any byte is read, and none of them was
    true of `bundle_dir / filename`:

    1. The name is relative. `Path('/etc/passwd')` joined onto a directory is
       `/etc/passwd`, so an absolute name silently left the bundle.
    2. It resolves inside the bundle. `../../secrets.jsonl` does not.
    3. A checksum covers it. Verification only proves the bundle's *own*
       inventory is intact; reading anything outside that inventory means
       scoring evidence nothing vouched for.
    """
    if not isinstance(filename, str) or not filename:
        raise BundleError(
            f"{MANIFEST_FILENAME}: files.{role} must be a non-empty relative "
            f"path inside the bundle"
        )
    bundle_dir = Path(bundle_dir)
    if Path(filename).is_absolute():
        raise BundleError(
            f"{MANIFEST_FILENAME} declares files.{role} = '{filename}', an "
            f"absolute path. A bundle may only name evidence inside itself."
        )
    root = bundle_dir.resolve()
    try:
        name = (bundle_dir / filename).resolve().relative_to(root).as_posix()
    except ValueError:
        raise BundleError(
            f"{MANIFEST_FILENAME} declares files.{role} = '{filename}', which "
            f"resolves outside the bundle directory. A bundle may only name "
            f"evidence inside itself."
        ) from None
    if name not in covered:
        raise BundleError(
            f"{MANIFEST_FILENAME} declares files.{role} = '{filename}', which "
            f"no checksum in {CHECKSUMS_FILENAME} covers. Nothing is read from "
            f"a bundle unless the sealed manifest vouches for its bytes; "
            f"re-seal the bundle with `plumbline seal`."
        )
    path = bundle_dir / name
    if path.is_symlink() or not path.is_file():
        raise BundleError(
            f"{MANIFEST_FILENAME} declares files.{role} = '{filename}', which "
            f"is not a regular file in the bundle"
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
            if raw["behavior"] == "answer" and not str(
                    raw.get("expected") or "").strip():
                # Blank is checked after stripping: a reference answer of
                # "   " is not a reference answer, and one that survives to
                # scoring makes an empty response look like a perfect match.
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
            forbidden_claims = raw.get("forbidden_claims", [])
            if not isinstance(forbidden_claims, list) or not all(
                    isinstance(s, str) for s in forbidden_claims):
                raise BundleError(
                    f"{path.name}:{lineno}: 'forbidden_claims' must be a list "
                    f"of strings the response must not assert"
                )
            blank = [s for s in forbidden + forbidden_claims if not s.strip()]
            if blank:
                # A blank needle matches every response, or no response,
                # depending on which screen reads it. Either way the item
                # declares a check that is not one.
                raise BundleError(
                    f"{path.name}:{lineno}: item '{raw['id']}' declares an "
                    f"empty forbidden string; a screen for nothing is not a "
                    f"screen"
                )
            t = raw.get("translation")
            if t is not None and t.get("review") not in REVIEW_STATUSES:
                raise BundleError(
                    f"{path.name}:{lineno}: translation.review must be one of {REVIEW_STATUSES}"
                )
            turns = raw.get("turns", [])
            if not isinstance(turns, list) or not all(
                    isinstance(s, str) for s in turns):
                raise BundleError(
                    f"{path.name}:{lineno}: 'turns' must be a list of "
                    f"follow-up user-turn strings"
                )
            if any(not s.strip() for s in turns):
                raise BundleError(
                    f"{path.name}:{lineno}: item '{raw['id']}' declares a "
                    f"blank turn; a conversation turn with nothing in it is "
                    f"not a turn"
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
                turns=turns,
                forbidden=forbidden,
                forbidden_claims=forbidden_claims,
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


def _parse_responses(path: Path, items: list[Item]
                     ) -> tuple[dict[str, str], dict[str, list[str]]]:
    by_id = {i.id: i for i in items}
    responses: dict[str, str] = {}
    turn_responses: dict[str, list[str]] = {}
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
            if raw["id"] not in by_id:
                raise BundleError(f"{path.name}:{lineno}: response for unknown item '{raw['id']}'")
            if raw["id"] in responses:
                raise BundleError(f"{path.name}:{lineno}: duplicate response for '{raw['id']}'")
            responses[raw["id"]] = raw["response"]
            item = by_id[raw["id"]]
            recorded_turns = raw.get("turn_responses")
            if recorded_turns is None:
                continue
            if not isinstance(recorded_turns, list) or not all(
                    isinstance(s, str) for s in recorded_turns):
                raise BundleError(
                    f"{path.name}:{lineno}: 'turn_responses' must be a list "
                    f"of strings, one per user turn"
                )
            expected_turns = 1 + len(item.turns)
            if len(recorded_turns) != expected_turns:
                raise BundleError(
                    f"{path.name}:{lineno}: item '{raw['id']}' declares "
                    f"{expected_turns} user turn(s) but 'turn_responses' has "
                    f"{len(recorded_turns)}; they must be recorded 1:1 or "
                    f"not at all"
                )
            # `response` and `turn_responses[-1]` are not cross-checked for
            # equality on purpose: `response` is independent evidence every
            # other suite reads, and a caller that redacts, truncates or
            # otherwise rewrites just the top-level response (a partial-
            # silence drill, a retention redaction) has not corrupted
            # anything `conversational_integrity` reads. They agree in the
            # ordinary case because whatever wrote both wrote them from the
            # same conversation; nothing here assumes they must.
            turn_responses[raw["id"]] = recorded_turns
    return responses, turn_responses


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

    dataset_sha256, covered = _verify(bundle_dir)

    if MANIFEST_FILENAME not in covered:
        raise BundleError(f"missing {MANIFEST_FILENAME}")
    manifest_path = bundle_dir / MANIFEST_FILENAME
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

    items = _parse_items(
        sealed_path(bundle_dir, items_name, "items", covered))
    responses, turn_responses = (
        _parse_responses(
            sealed_path(bundle_dir, responses_name, "responses", covered),
            items)
        if responses_name else ({}, {})
    )

    sources_name = files.get("sources")
    sources = (_parse_sources(
        sealed_path(bundle_dir, sources_name, "sources", covered))
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
        turn_responses=turn_responses,
        sources=sources,
        covered=covered,
    )
