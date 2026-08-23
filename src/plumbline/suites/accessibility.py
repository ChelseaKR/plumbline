"""Accessibility of the interface under test: structural checks on a real
HTML snapshot committed inside the evidence bundle.

The bundle's manifest may declare `files.interface`, an HTML capture of the
interface the recorded conversation happened in. It is hashed with everything
else, so the interface that was audited is pinned as firmly as the answers
were.

Five checks, all structural, all decidable from markup:

1. **Language declaration** — the root element declares a language. Without
   it a screen reader guesses, and a Spanish answer read aloud in an English
   voice is not a Spanish answer.
2. **Labels** — every form control has an accessible name.
3. **Live region** — something announces new messages. A chat interface whose
   replies arrive silently is unusable non-visually, and this is the check
   that is almost always missing.
4. **Heading order** — exactly one `h1`, no skipped levels.
5. **Contrast** — the snapshot declares its colour pairs in a JSON block and
   Plumbline computes the WCAG ratios itself. An undeclared palette fails:
   unverified contrast is not passing contrast.

Contrast is computed, not taken on trust, because a self-reported "we meet AA"
is not evidence. The declaration supplies the colour pairs; the arithmetic is
this module's.

The score is a **census**, not a sample: five fixed checks, exhaustively run.
The report therefore carries no confidence interval for this suite and says
why — there is no sampling error to report, and a longer checklist would not
narrow one.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser

from ..bundle import Bundle
from ..judges import Judge
from ..stats import KIND_CENSUS
from . import Suite, SuiteResult, register

CONTRAST_SCRIPT_ID = "plumbline-contrast"
AA_NORMAL = 4.5
AA_LARGE = 3.0

LIVE_ROLES = {"status", "alert", "log"}
LIVE_POLITENESS = {"polite", "assertive"}
CONTROL_TAGS = {"input", "select", "textarea"}
# Controls whose visible text supplies their name.
SELF_NAMING_INPUT_TYPES = {"submit", "reset", "button", "image"}


def relative_luminance(hex_color: str) -> float:
    """WCAG 2.x relative luminance of an #rgb or #rrggbb colour."""
    value = hex_color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        raise ValueError(f"not a hex colour: {hex_color!r}")
    channels = []
    for i in (0, 2, 4):
        c = int(value[i:i + 2], 16) / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    a = relative_luminance(foreground)
    b = relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


class _Snapshot(HTMLParser):
    """Collects only what the five checks need."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root_lang: str | None = None
        self.controls: list[tuple[str, dict[str, str]]] = []
        self.label_targets: set[str] = set()
        self.live_regions: list[str] = []
        self.headings: list[int] = []
        self.ids: set[str] = set()
        self._in_contrast_script = False
        self.contrast_json: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {k.lower(): (v or "") for k, v in attrs}
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        if tag == "html":
            self.root_lang = attributes.get("lang") or None
        elif tag in CONTROL_TAGS:
            self.controls.append((tag, attributes))
        elif tag == "label" and attributes.get("for"):
            self.label_targets.add(attributes["for"])
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.headings.append(int(tag[1]))
        elif tag == "script" and attributes.get("id") == CONTRAST_SCRIPT_ID:
            self._in_contrast_script = True
        if (attributes.get("aria-live", "").lower() in LIVE_POLITENESS
                or attributes.get("role", "").lower() in LIVE_ROLES):
            self.live_regions.append(
                attributes.get("id") or attributes.get("role") or tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_contrast_script = False

    def handle_data(self, data: str) -> None:
        if self._in_contrast_script:
            self.contrast_json = (self.contrast_json or "") + data


def _check_language(snapshot: _Snapshot) -> tuple[bool, str]:
    if snapshot.root_lang:
        return True, f"root element declares lang=\"{snapshot.root_lang}\""
    return False, "the root element declares no language"


def _check_labels(snapshot: _Snapshot) -> tuple[bool, str]:
    unnamed = []
    for tag, attributes in snapshot.controls:
        input_type = attributes.get("type", "text").lower()
        if tag == "input" and input_type == "hidden":
            continue
        named = bool(
            attributes.get("aria-label")
            or attributes.get("aria-labelledby")
            or attributes.get("title")
            or (attributes.get("id") and attributes["id"] in snapshot.label_targets)
            or (tag == "input" and input_type in SELF_NAMING_INPUT_TYPES
                and (attributes.get("value") or attributes.get("alt")))
        )
        if not named:
            unnamed.append(attributes.get("id") or f"<{tag}>")
    if not snapshot.controls:
        return False, "the snapshot contains no form controls to label"
    if unnamed:
        return False, f"controls with no accessible name: {', '.join(unnamed)}"
    return True, f"all {len(snapshot.controls)} controls have an accessible name"


def _check_live_region(snapshot: _Snapshot) -> tuple[bool, str]:
    if snapshot.live_regions:
        return True, f"live regions: {', '.join(snapshot.live_regions)}"
    return False, ("nothing announces new messages: no aria-live=polite/"
                   "assertive and no role of status, alert or log")


def _check_heading_order(snapshot: _Snapshot) -> tuple[bool, str]:
    if not snapshot.headings:
        return False, "the snapshot has no headings"
    top_level = snapshot.headings.count(1)
    if top_level != 1:
        return False, f"expected exactly one h1, found {top_level}"
    previous = snapshot.headings[0]
    for level in snapshot.headings[1:]:
        if level > previous + 1:
            return False, f"heading level jumps from h{previous} to h{level}"
        previous = level
    return True, (f"one h1 and no skipped levels across "
                  f"{len(snapshot.headings)} headings")


def _check_contrast(snapshot: _Snapshot) -> tuple[bool, str]:
    if not snapshot.contrast_json or not snapshot.contrast_json.strip():
        return False, (f"no <script type=\"application/json\" "
                       f"id=\"{CONTRAST_SCRIPT_ID}\"> declaring colour pairs; "
                       f"unverified contrast is not passing contrast")
    try:
        pairs = json.loads(snapshot.contrast_json)
    except json.JSONDecodeError as e:
        return False, f"the contrast declaration is not valid JSON: {e}"
    if not isinstance(pairs, list) or not pairs:
        return False, "the contrast declaration lists no colour pairs"
    failures = []
    for pair in pairs:
        try:
            required = AA_LARGE if pair.get("size") == "large" else AA_NORMAL
            ratio = contrast_ratio(pair["foreground"], pair["background"])
        except (KeyError, TypeError, ValueError) as e:
            return False, f"unreadable colour pair {pair!r}: {e}"
        if ratio < required:
            failures.append(
                f"{pair.get('name', 'unnamed')} {ratio:.2f}:1 "
                f"(needs {required}:1)"
            )
    if failures:
        return False, "; ".join(failures)
    return True, f"all {len(pairs)} declared colour pairs meet WCAG AA"


CHECKS = (
    ("language_declaration", _check_language),
    ("control_labels", _check_labels),
    ("live_region", _check_live_region),
    ("heading_order", _check_heading_order),
    ("contrast_declarations", _check_contrast),
)


@register
class AccessibilitySuite(Suite):
    id = "accessibility"
    # 1.00: these are structural minimums, not a quality gradient. Four out of
    # five means one population cannot use the interface.
    default_floor = 1.00

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        interface_name = bundle.manifest.get("files", {}).get("interface")
        if not interface_name:
            self.require_population(
                [],
                "the bundle manifest declares no `files.interface`, so there "
                "is no captured interface to check",
            )
        # Through the bundle, never `bundle.path / name`: the interface is
        # evidence, so it has to be inside the bundle and covered by a
        # checksum before a byte of it is parsed.
        path = bundle.sealed(interface_name, "interface")

        snapshot = _Snapshot()
        snapshot.feed(path.read_text(encoding="utf-8"))
        snapshot.close()

        records, sample = [], []
        failed = []
        for name, check in CHECKS:
            passed, detail = check(snapshot)
            sample.append(1.0 if passed else 0.0)
            records.append({
                "check": name,
                "score": 1.0 if passed else 0.0,
                "detail": detail,
            })
            if not passed:
                failed.append(name)

        score = sum(sample) / len(sample)
        return SuiteResult(
            suite_id=self.id,
            score=score,
            floor=floor,
            verdict=self.verdict_for(score, floor),
            n=len(sample),
            details={
                "interface": interface_name,
                "metric": "fraction of structural checks passed",
                "failed_checks": failed,
                "contrast_note": (
                    "contrast ratios are computed here from the colour pairs "
                    "the snapshot declares, not taken from a self-reported "
                    "claim; an undeclared palette fails the check"
                ),
                "scope_note": (
                    "structural checks on a captured snapshot. They do not "
                    "replace testing with assistive technology or with "
                    "disabled users, and passing them is a floor, not a "
                    "finding of accessibility"
                ),
            },
            item_records=records,
            score_kind=KIND_CENSUS,
            sample=sample,
        )
