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
2. **Labels** — every form control has an accessible name, `<button>`
   included. A button usually names itself with its own text, so this check
   reads that text the way a browser's accessible name computation does:
   an `aria-hidden="true"` subtree contributes nothing, a script block
   contributes nothing, and a `<button>` with no end tag has no readable
   name at all rather than every word that follows it on the page.
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
from dataclasses import dataclass, field
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
CONTROL_TAGS = {"input", "select", "textarea", "button"}
# Controls whose visible text supplies their name.
SELF_NAMING_INPUT_TYPES = {"submit", "reset", "button", "image"}
# Elements the HTML specification gives no end tag. A parser that tracked
# nesting without knowing them would leave every one of them open forever,
# and the document's first `<br>` would appear to contain the rest of it.
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
# Text in these is never rendered, so it never names anything.
NON_RENDERED_TAGS = {"script", "style", "template", "noscript"}


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


@dataclass
class _Control:
    """One form control and whatever the markup offers as its name.

    `content_name` is filled only for `<button>`, whose own text is its
    accessible name. `closed` records whether an explicit `</button>` ever
    arrived: without one the text collected is the remainder of the
    document rather than the button's label, so it names nothing.
    `discounted_text` remembers that text was seen and deliberately not
    counted, so the failure can say why instead of only that it failed.
    """

    tag: str
    attributes: dict[str, str] = field(default_factory=dict)
    content_name: str = ""
    closed: bool = True
    discounted_text: bool = False


@dataclass
class _Element:
    """One open element, tracked for the two questions that need nesting:
    whether this point in the document is inside an `aria-hidden` subtree,
    and which button, if any, text landing here belongs to."""

    tag: str
    hidden: bool
    control: _Control | None


class _Snapshot(HTMLParser):
    """Collects only what the five checks need."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root_lang: str | None = None
        self.controls: list[_Control] = []
        self.label_targets: set[str] = set()
        self.live_regions: list[str] = []
        self.headings: list[int] = []
        self.ids: set[str] = set()
        self._in_contrast_script = False
        self.contrast_json: str | None = None
        self._open: list[_Element] = []
        self._hidden_depth = 0

    def _innermost_button(self) -> _Control | None:
        for element in reversed(self._open):
            if element.control is not None and element.control.tag == "button":
                return element.control
        return None

    def _offer_name_text(self, text: str, *, hidden: bool) -> None:
        """Offer text to the innermost open button as part of its name.

        Text assistive technology will never announce is not offered: an
        `aria-hidden="true"` subtree is excluded from the accessible name
        computation, so counting it here would report a button whose only
        text is hidden as a button with a name.
        """
        button = self._innermost_button()
        if button is None:
            return
        if hidden or self._hidden_depth:
            if text.strip():
                button.discounted_text = True
            return
        button.content_name += text

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {k.lower(): (v or "") for k, v in attrs}
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        hidden = attributes.get("aria-hidden", "").strip().lower() == "true"
        control: _Control | None = None
        if tag == "html":
            self.root_lang = attributes.get("lang") or None
        elif tag in CONTROL_TAGS:
            control = _Control(tag=tag, attributes=attributes,
                               closed=tag != "button")
            self.controls.append(control)
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
        # An image inside a button contributes its alt text to the button's
        # name, exactly as the accessible name computation does. Without
        # this, an icon button labelled the correct way would be reported
        # unnamed, and a check that fails correct markup gets switched off.
        if tag == "img":
            self._offer_name_text(f" {attributes.get('alt', '')} ", hidden=hidden)
        if tag not in VOID_TAGS:
            self._open.append(_Element(tag=tag, hidden=hidden, control=control))
            if hidden:
                self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_contrast_script = False
        if tag in VOID_TAGS:
            return
        index = -1
        for position in range(len(self._open) - 1, -1, -1):
            if self._open[position].tag == tag:
                index = position
                break
        if index < 0:
            # An end tag with no start tag closes nothing.
            return
        matched = self._open[index]
        if matched.control is not None and matched.tag == "button":
            matched.control.closed = True
        # Everything above the match was left open by the markup. Those
        # elements are closed here too, but implicitly: a button among them
        # keeps `closed = False`, because nothing in the document ever said
        # where its label stopped.
        for element in self._open[index:]:
            if element.hidden:
                self._hidden_depth -= 1
        del self._open[index:]

    def handle_data(self, data: str) -> None:
        if self._in_contrast_script:
            self.contrast_json = (self.contrast_json or "") + data
        if self._open and self._open[-1].tag in NON_RENDERED_TAGS:
            return
        self._offer_name_text(data, hidden=False)


def _check_language(snapshot: _Snapshot) -> tuple[bool, str]:
    if snapshot.root_lang:
        return True, f"root element declares lang=\"{snapshot.root_lang}\""
    return False, "the root element declares no language"


def _why_unnamed(control: _Control) -> str:
    """Name the control, and for a button say what was rejected and why.

    A bare list of ids tells an author which control is unnamed but not
    which of the two silent ways it got there, and both look like working
    markup in a browser.
    """
    name = control.attributes.get("id") or f"<{control.tag}>"
    if control.tag != "button":
        return name
    if not control.closed:
        return (f"{name} (no </button>, so the text after it is the rest of "
                f"the document rather than this button's name)")
    if control.discounted_text and not control.content_name.strip():
        return f'{name} (its only text is inside aria-hidden="true")'
    return name


def _check_labels(snapshot: _Snapshot) -> tuple[bool, str]:
    unnamed = []
    for control in snapshot.controls:
        tag, attributes = control.tag, control.attributes
        input_type = attributes.get("type", "text").lower()
        if tag == "input" and input_type == "hidden":
            continue
        named = bool(
            attributes.get("aria-label", "").strip()
            or attributes.get("aria-labelledby", "").strip()
            or attributes.get("title", "").strip()
            or (attributes.get("id") and attributes["id"] in snapshot.label_targets)
            or (tag == "input" and input_type in SELF_NAMING_INPUT_TYPES
                and (attributes.get("value") or attributes.get("alt")))
            or (tag == "button" and control.closed
                and control.content_name.strip())
        )
        if not named:
            unnamed.append(_why_unnamed(control))
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
