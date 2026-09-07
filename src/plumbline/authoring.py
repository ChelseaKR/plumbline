"""Drafting a question set, and suggesting declarations for an existing one.

Two commands with one purpose: lower the cost of the human work an audit
cannot do for itself, without moving any part of that work into the
instrument.

**`author`** turns a source corpus into a question set skeleton — one draft
item per passage per language, with `prompt` and `expected` deliberately
blank, `answering_sources` prefilled with the passage the item was drafted
from, `fact_id` shared across languages drafted from the same passage, and
`review: "draft"` on every item. A person writes the questions. Nothing here
writes a question, and nothing here writes a reference answer: a generated
prompt graded against a generated expectation is a harness measuring itself.

`review: "draft"` is the safety catch. A draft item is exempt from the rule
that an answer item must carry a non-blank `expected`, because that is what
being a draft means — and `audit`, `gate` and `record` refuse outright any
bundle that still contains one (`bundle.refuse_drafts`). The exemption
therefore exists only in a state that cannot be scored and cannot be
recorded against, which is the only shape in which it is safe: a blank
reference answer that reached scoring would make an empty response look like
a perfect match, and a blank prompt that reached `record` would send the live
target nothing and file the silence as an answer.

**`suggest-declarations`** is the other half of the same idea, for a bundle
that already has items. `passage_attribution` already computes, and already
refuses to score, a suggestion of which passage answers an item — see
`suites/attribution.py`'s `_suggestions` and the note beside it. This
publishes those suggestions as a worksheet a person reviews, and writes
nothing back into the bundle.

Two properties the sheet is built around:

- **Every undeclared item gets a row.** A sheet that silently omitted the
  items it could not rank would report a suggestion rate over whatever was
  left and read exactly like a sheet that considered everything.
- **A row that made no comparison says so, in words.** `undetermined`
  means two passages were compared and came out within the decision margin.
  `single_candidate` and `no_reference_answer` mean no comparison happened
  at all, and their margin cell reads `not computed` rather than `0.0000` —
  a zero there is a measured tie, and these are not one.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import bundle as bundle_mod
from .bundle import Bundle, Item, Source
from .judges import Judge
from .suites.attribution import DECISION_MARGIN

#: Manifest `version` for a freshly drafted question set. A constant, not a
#: date: `author` writes byte-identical output for identical input, and a
#: timestamp in the manifest would make two identical drafting runs produce
#: two different bundle hashes.
DRAFT_VERSION = "0.0.0-draft"

ITEMS_FILENAME = "items.jsonl"
SOURCES_FILENAME = "sources.jsonl"

#: Why a row carries no suggestion. Values are the literal text printed in
#: the `suggestion` column, so a reader never has to map a code to a meaning.
UNDETERMINED = "undetermined"
SINGLE_CANDIDATE = "single_candidate"
NO_REFERENCE_ANSWER = "no_reference_answer"

#: Printed in the margin column of a row where no comparison was made. Not
#: `0.0000`: a zero margin is a measured tie between two passages, and a row
#: that never compared two passages has not measured one.
NOT_COMPUTED = "not computed"


class AuthoringUsageError(Exception):
    """The command was invoked in a way that cannot mean anything (exit 2)."""


def draft_items(sources: Sequence[Source], languages: Sequence[str]
                ) -> list[dict[str, Any]]:
    """Draft item records: one per passage per language, in a fixed order.

    Passages in the order the corpus declares them, languages in the order
    given on the command line — both inputs, so identical invocations produce
    identical bytes. The first language given is the primary one; every other
    language's item carries a `translation` block pointing at the primary
    item and marked `unreviewed`, which is what it is: a slot for a
    translation nobody has written yet, and one the existing
    unreviewed-translation warning will report on every run until someone
    does.
    """
    primary = languages[0]
    drafted: list[dict[str, Any]] = []
    for source in sources:
        for lang in languages:
            record: dict[str, Any] = {
                "id": f"{source.id}-{lang}",
                "lang": lang,
                "behavior": "answer",
                # Blank on purpose, and the reason `review` is set below.
                "prompt": "",
                "expected": "",
                "fact_id": f"fact-{source.id}",
                "sources": [source.id],
                # The passage this item was drafted from is the obvious
                # candidate for the one that answers it, and it is a
                # *starting point for a person*, not a finding: the item has
                # no question in it yet, so nothing has been checked.
                "answering_sources": [source.id],
                "review": bundle_mod.ITEM_REVIEW_DRAFT,
            }
            if lang != primary:
                record["translation"] = {
                    "of": f"{source.id}-{primary}",
                    "review": "unreviewed",
                }
            drafted.append(record)
    return drafted


def draft_manifest(name: str, item_count: int, languages: Sequence[str]
                   ) -> dict[str, Any]:
    return {
        "format": bundle_mod.BUNDLE_FORMAT,
        "format_version": bundle_mod.FORMAT_VERSION,
        "name": name,
        "version": DRAFT_VERSION,
        "synthetic": False,
        "description": (
            f"Question-set skeleton drafted by `plumbline author` from a "
            f"source corpus: {item_count} draft items across "
            f"{', '.join(languages)}. Every item carries "
            f"`review: \"{bundle_mod.ITEM_REVIEW_DRAFT}\"` and a blank "
            f"`prompt` and `expected`, which a person writes. `audit`, "
            f"`gate` and `record` refuse this bundle until every draft "
            f"marker is gone."
        ),
        "files": {"items": ITEMS_FILENAME, "sources": SOURCES_FILENAME},
    }


def write_question_set(*, sources_path: Path, out_dir: Path,
                       languages: Sequence[str], name: str) -> dict[str, Any]:
    """Draft a sealed question-set bundle. Returns its checksum record.

    The corpus is copied in rather than referenced: a question set that
    pointed at a passage file outside itself would be a bundle whose evidence
    its own checksums do not cover.
    """
    if not languages:
        raise AuthoringUsageError("at least one --lang is required")
    duplicates = sorted({lang for lang in languages
                         if list(languages).count(lang) > 1})
    if duplicates:
        raise AuthoringUsageError(
            f"--lang given more than once for {', '.join(duplicates)}; each "
            f"language drafts one item per passage, so a repeat would draft "
            f"two items with the same id"
        )

    sources_path = Path(sources_path)
    if not sources_path.is_file():
        raise AuthoringUsageError(f"source corpus not found: {sources_path}")
    corpus = bundle_mod.parse_sources(sources_path)
    if not corpus:
        # The one that would otherwise pass quietly: an empty corpus drafts
        # zero items, seals a bundle with an empty items file, and `validate`
        # then refuses it with a message about the bundle rather than about
        # the corpus that produced it.
        raise AuthoringUsageError(
            f"{sources_path} declares no passages, so there is nothing to "
            f"draft a question about. An empty question set is not a "
            f"question set."
        )

    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise AuthoringUsageError(
            f"{out_dir} already exists and is not empty; drafting into it "
            f"would mix a new skeleton with whatever is there. Choose an "
            f"empty directory."
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    ordered = list(corpus.values())
    items = draft_items(ordered, languages)
    _write_jsonl(out_dir / ITEMS_FILENAME, items)
    _write_jsonl(out_dir / SOURCES_FILENAME, [_source_record(s) for s in ordered])
    manifest = draft_manifest(name, len(items), languages)
    with open(out_dir / bundle_mod.MANIFEST_FILENAME, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return bundle_mod.seal(out_dir)


def _source_record(source: Source) -> dict[str, Any]:
    record: dict[str, Any] = {"id": source.id}
    if source.title is not None:
        record["title"] = source.title
    if source.url is not None:
        record["url"] = source.url
    record["text"] = source.text
    return record


def _write_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class Suggestion:
    """One row of the worksheet. `margin` is None when nothing was compared."""
    item_id: str
    lang: str
    suggestion: str
    margin: float | None
    runner_up: str | None
    candidates: int

    @property
    def is_declaration(self) -> bool:
        """Whether `suggestion` names a passage rather than a reason."""
        return self.suggestion not in (
            UNDETERMINED, SINGLE_CANDIDATE, NO_REFERENCE_ANSWER)


def suggestions_for(bundle: Bundle, judge: Judge) -> list[Suggestion]:
    """A row for every answer item that declares no `answering_sources`.

    Ranked by the *reference answer* against each candidate passage, which is
    the same computation `passage_attribution` already refuses to score, for
    the same reason: inferring the answering passage from the reference answer
    is often right, unsound, and silent when it is wrong.
    """
    rows: list[Suggestion] = []
    for item in _undeclared(bundle.items):
        candidates = bundle.sources_for(item)
        if len(candidates) < 2:
            rows.append(Suggestion(
                item_id=item.id, lang=item.lang, suggestion=SINGLE_CANDIDATE,
                margin=None, runner_up=None, candidates=len(candidates)))
            continue
        if not (item.expected or "").strip():
            rows.append(Suggestion(
                item_id=item.id, lang=item.lang,
                suggestion=NO_REFERENCE_ANSWER, margin=None, runner_up=None,
                candidates=len(candidates)))
            continue
        ranked = sorted(
            ((judge.support_score(item.expected or "", c.text), c.id)
             for c in candidates),
            key=lambda pair: (-pair[0], pair[1]),
        )
        margin = ranked[0][0] - ranked[1][0]
        rows.append(Suggestion(
            item_id=item.id, lang=item.lang,
            suggestion=(ranked[0][1] if margin >= DECISION_MARGIN
                        else UNDETERMINED),
            margin=round(margin, 4), runner_up=ranked[1][1],
            candidates=len(candidates)))
    return rows


def _undeclared(items: Sequence[Item]) -> list[Item]:
    """Answer items with passages and no `answering_sources`, in item order."""
    return [i for i in items
            if i.behavior == "answer" and i.sources and not i.answering_sources]


def render_sheet(bundle: Bundle, rows: Sequence[Suggestion]) -> str:
    """The worksheet, as Markdown. Byte-identical for identical input."""
    answerable = [i for i in bundle.items if i.behavior == "answer" and i.sources]
    declared = len(answerable) - len(rows)
    named = [r for r in rows if r.is_declaration]

    lines = [
        "# Suggested `answering_sources` declarations",
        "",
        f"Bundle: `{bundle.name}` (dataset `{bundle.dataset_id}`, sha256 "
        f"`{bundle.dataset_sha256}`)",
        "",
        "**Nothing here is a declaration, and nothing was written into the "
        "bundle.** Each suggestion is computed from the item's *reference "
        "answer*, not from the target's response, by the deterministic "
        "lexical judge. That inference is often right, unsound, and silent "
        "when it is wrong, which is why `passage_attribution` will not score "
        "it. Adopting a row without reading the passage would have the suite "
        "grading answers against an expectation this file invented.",
        "",
        f"Answer items with passages: **{len(answerable)}**. Already "
        f"declaring `answering_sources`: **{declared}**. Undeclared, listed "
        f"below: **{len(rows)}**, of which **{len(named)}** have a suggestion "
        f"and **{len(rows) - len(named)}** do not.",
        "",
        f"A suggestion is named only when the best passage accounts for the "
        f"reference answer by at least the decision margin "
        f"(**{DECISION_MARGIN}**) better than the runner-up.",
        "",
    ]
    if not rows:
        lines += [
            "Every answer item with passages already declares "
            "`answering_sources`. There is nothing to review.",
            "",
        ]
    else:
        lines += [
            "| item | lang | suggestion | margin | runner-up | candidates |",
            "|---|---|---|---|---|---|",
        ]
        for row in rows:
            margin = NOT_COMPUTED if row.margin is None else f"{row.margin:.4f}"
            runner_up = f"`{row.runner_up}`" if row.runner_up else NOT_COMPUTED
            suggestion = (f"`{row.suggestion}`" if row.is_declaration
                          else row.suggestion)
            lines.append(
                f"| `{row.item_id}` | {row.lang} | {suggestion} | {margin} | "
                f"{runner_up} | {row.candidates} |"
            )
        lines += [
            "",
            "Rows that name no passage:",
            "",
            f"- `{UNDETERMINED}` — two passages were compared and came out "
            f"within {DECISION_MARGIN} of each other. A comparison that close "
            f"is one a lexical judge cannot make, so no passage is named.",
            f"- `{SINGLE_CANDIDATE}` — the item has fewer than two passages, "
            f"so there is no wrong paragraph an answer could have come from "
            f"and nothing to choose between.",
            f"- `{NO_REFERENCE_ANSWER}` — the item carries no reference "
            f"answer, so there is nothing to rank the passages against.",
            "",
            f"The last two made no comparison at all; their margin reads "
            f"`{NOT_COMPUTED}` rather than `0.0000`, because a zero margin "
            f"means two passages tied and these did not.",
            "",
        ]
    return "\n".join(lines)
