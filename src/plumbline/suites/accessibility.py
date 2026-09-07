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
5. **Contrast** — Plumbline computes the WCAG ratios itself, from one of two
   sources. An undeclared palette fails: unverified contrast is not passing
   contrast.

Contrast is computed, not taken on trust, because a self-reported "we meet AA"
is not evidence. The arithmetic is always this module's; what differs is where
the colour pairs came from, and that difference is worth stating plainly because
one of the two sources cannot be complete.

**Declared pairs** (`plumbline-contrast`) are a list the snapshot writes about
itself. The ratios are real, but the *population* is not: a page whose hint text
fails AA can simply leave that pair out and pass, and nothing in a markup-only
check can notice, because reading colours out of the page's CSS would mean
shipping a cascade implementation. That is why this path now carries a caveat
into every record and into the report rather than reading as a clean pass.

**Computed pairs** (`plumbline-computed-contrast`) come from a renderer that
already has a cascade: `tools/capture_interface.py` loads the page in a browser
and records the computed foreground and background of every text node. The
capture lives outside the harness and outside the gate — it is an input, the same
way a recording is — and the gate imports nothing from it.

The marker on a computed block is not taken at its word either. `source:
computed` is a claim anyone can type, so the block is checked against the
snapshot it sits in: every element in the markup that carries rendered text must
appear in the block, either as a measured pair or as an explicitly skipped node
with a reason. **Omitting the failing pair is what this defends against, and
omission is exactly what the completeness check sees.** An empty block is a
failure, not a pass: a capture that recorded nothing is not a capture that found
nothing wrong.

The score is a **census**, not a sample: five fixed checks, exhaustively run.
The report therefore carries no confidence interval for this suite and says
why — there is no sampling error to report, and a longer checklist would not
narrow one.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser

from ..bundle import Bundle
from ..judges import Judge
from ..stats import KIND_CENSUS
from . import Suite, SuiteResult, register

CONTRAST_SCRIPT_ID = "plumbline-contrast"
COMPUTED_SCRIPT_ID = "plumbline-computed-contrast"
SOURCE_DECLARED = "declared"
SOURCE_COMPUTED = "computed"
#: What the report and every item record say when the pairs are the page's own.
DECLARED_CAVEAT = (
    "self-declared pairs: the colour pairs came from a block the snapshot "
    "writes about itself, so the ratios are measured but the population is "
    "not verified — a pair that fails can be left out of the list"
)
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


def normalise_text(text: str) -> str:
    """One rendered text run, as both sides of the completeness check see it.

    Whitespace runs collapse to a single space and the ends are stripped,
    which is what a browser renders and what an HTML parser hands back. The
    capture tool applies the identical rule in JavaScript, and
    ``tests/test_accessibility.py`` holds the two to the same fixture, because
    a completeness check whose two sides normalise differently reports every
    snapshot as incomplete and gets switched off.
    """
    return " ".join(text.split())


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
        self._in_computed_script = False
        self.computed_json: str | None = None
        self._in_head = False
        # Every run of rendered text in the markup, normalised, in document
        # order. This is the population a computed block has to account for.
        self.text_runs: list[str] = []
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
        elif tag == "script" and attributes.get("id") == COMPUTED_SCRIPT_ID:
            self._in_computed_script = True
        elif tag == "head":
            # `<title>` is text and is never painted into the page, so a
            # renderer records no colour pair for it. Counting it as a text run
            # the capture had to account for would make every honest capture
            # look incomplete. A document with no `<head>` excludes nothing.
            self._in_head = True
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
            self._in_computed_script = False
        if tag == "head":
            self._in_head = False
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
        if self._in_computed_script:
            self.computed_json = (self.computed_json or "") + data
        if self._open and self._open[-1].tag in NON_RENDERED_TAGS:
            return
        run = normalise_text(data)
        if run and not self._in_head:
            self.text_runs.append(run)
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


def _ratio_failures(pairs: list[object], label: str) -> tuple[list[str], str]:
    """WCAG AA failures among ``pairs``, or the reason none could be computed.

    The arithmetic is the same whichever source the pairs came from; only the
    completeness of the list differs, and that is decided by the caller.
    """
    failures = []
    for pair in pairs:
        if not isinstance(pair, dict):
            return [], f"unreadable {label} colour pair {pair!r}: not an object"
        try:
            required = AA_LARGE if pair.get("size") == "large" else AA_NORMAL
            ratio = contrast_ratio(pair["foreground"], pair["background"])
        except (KeyError, TypeError, ValueError) as e:
            return [], f"unreadable {label} colour pair {pair!r}: {e}"
        if ratio < required:
            failures.append(
                f"{pair.get('name') or pair.get('text') or 'unnamed'} "
                f"{ratio:.2f}:1 (needs {required}:1)"
            )
    return failures, ""


def _accounted_text(block: dict[str, object]) -> tuple[list[str], str]:
    """Every text run a computed block accounts for, measured or skipped.

    A renderer legitimately measures nothing for text the cascade never paints
    — ``display:none``, ``visibility:hidden``, a zero-sized box — so a capture
    may leave those out of ``pairs``. It may not leave them out silently: each
    goes in ``skipped`` with a reason, and the count reaches the report. That
    is the difference between a node the renderer decided was invisible and a
    node somebody decided not to mention.
    """
    accounted: list[str] = []
    pairs = block.get("pairs")
    if not isinstance(pairs, list):
        return [], "the computed block has no `pairs` list"
    for pair in pairs:
        if not isinstance(pair, dict) or not isinstance(pair.get("text"), str):
            return [], (f"computed pair {pair!r} carries no `text`, so it cannot be "
                        f"matched against the text the snapshot contains")
        accounted.append(normalise_text(pair["text"]))
    skipped = block.get("skipped", [])
    if not isinstance(skipped, list):
        return [], "the computed block's `skipped` is not a list"
    for entry in skipped:
        if (not isinstance(entry, dict) or not isinstance(entry.get("text"), str)
                or not str(entry.get("reason", "")).strip()):
            return [], (f"skipped node {entry!r} needs both `text` and a non-empty "
                        f"`reason`; a node dropped without a stated reason is "
                        f"indistinguishable from one left out")
        accounted.append(normalise_text(entry["text"]))
    return accounted, ""


def _check_computed_contrast(snapshot: _Snapshot) -> tuple[bool, str]:
    """Contrast from a renderer's computed styles, checked for completeness.

    Fails closed on every way the block can fail to be evidence: unparseable,
    not an object, not marked ``computed``, empty, or missing a text run the
    snapshot it sits in actually contains. That last one is the point of the
    whole exercise: a block that lists only its passing pairs is a block that
    is missing text, and missing text is visible from the markup.
    """
    assert snapshot.computed_json is not None
    try:
        block = json.loads(snapshot.computed_json)
    except json.JSONDecodeError as e:
        return False, f"the computed contrast block is not valid JSON: {e}"
    if not isinstance(block, dict):
        return False, "the computed contrast block is not a JSON object"
    if block.get("source") != SOURCE_COMPUTED:
        return False, (f"the computed contrast block declares source "
                       f"{block.get('source')!r}, not {SOURCE_COMPUTED!r}")
    pairs = block.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        return False, ("the computed contrast block measured no colour pairs; a "
                       "capture that recorded nothing is not a capture that found "
                       "nothing wrong")

    accounted, problem = _accounted_text(block)
    if problem:
        return False, problem
    missing = _missing_runs(snapshot.text_runs, accounted)
    if missing:
        shown = "; ".join(repr(run[:60]) for run in missing[:4])
        more = f" (and {len(missing) - 4} more)" if len(missing) > 4 else ""
        return False, (f"the computed block does not account for "
                       f"{len(missing)} of the {len(snapshot.text_runs)} text runs "
                       f"in this snapshot: {shown}{more}. Text present in the "
                       f"markup and absent from the capture is the shape a pair "
                       f"removed for failing would take")

    failures, unreadable = _ratio_failures(pairs, SOURCE_COMPUTED)
    if unreadable:
        return False, unreadable
    if failures:
        return False, "; ".join(failures)
    skipped = len(block.get("skipped", []) or [])
    skipped_note = f", {skipped} not painted by the renderer" if skipped else ""
    return True, (f"all {len(pairs)} computed colour pairs meet WCAG AA "
                  f"(every text run in the snapshot accounted for{skipped_note})")


def _missing_runs(present: list[str], accounted: list[str]) -> list[str]:
    """Text runs in the markup that the computed block does not account for.

    A multiset difference, not a set difference. The same sentence rendered
    twice in two different colours is two text runs and needs two entries; a
    set comparison would let the second, failing one be dropped.
    """
    remaining = Counter(accounted)
    missing = []
    for run in present:
        if remaining[run] > 0:
            remaining[run] -= 1
        else:
            missing.append(run)
    return missing


def _check_declared_contrast(snapshot: _Snapshot) -> tuple[bool, str]:
    if not snapshot.contrast_json or not snapshot.contrast_json.strip():
        return False, (f"no <script type=\"application/json\" "
                       f"id=\"{CONTRAST_SCRIPT_ID}\"> declaring colour pairs and no "
                       f"id=\"{COMPUTED_SCRIPT_ID}\" capture; "
                       f"unverified contrast is not passing contrast")
    try:
        pairs = json.loads(snapshot.contrast_json)
    except json.JSONDecodeError as e:
        return False, f"the contrast declaration is not valid JSON: {e}"
    if not isinstance(pairs, list) or not pairs:
        return False, "the contrast declaration lists no colour pairs"
    failures, unreadable = _ratio_failures(pairs, SOURCE_DECLARED)
    if unreadable:
        return False, unreadable
    if failures:
        return False, "; ".join(failures)
    return True, (f"all {len(pairs)} declared colour pairs meet WCAG AA "
                  f"[{DECLARED_CAVEAT}]")


def contrast_source(snapshot: _Snapshot) -> str:
    """Which block the contrast check will read. Computed wins when present.

    "Present" means the block exists, not that it is usable. A computed block
    that cannot be read is a failure of the computed check, never a reason to
    quietly fall back to the page's own account of itself — falling back would
    make a broken capture score identically to a good one.
    """
    if snapshot.computed_json is not None and snapshot.computed_json.strip():
        return SOURCE_COMPUTED
    return SOURCE_DECLARED


def _check_contrast(snapshot: _Snapshot) -> tuple[bool, str]:
    if contrast_source(snapshot) == SOURCE_COMPUTED:
        return _check_computed_contrast(snapshot)
    return _check_declared_contrast(snapshot)


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

        source = contrast_source(snapshot)
        records, sample = [], []
        failed = []
        for name, check in CHECKS:
            passed, detail = check(snapshot)
            sample.append(1.0 if passed else 0.0)
            record = {
                "check": name,
                "score": 1.0 if passed else 0.0,
                "detail": detail,
            }
            if name == "contrast_declarations":
                # Which source produced this verdict travels with the verdict.
                # A reader who sees only the score cannot tell a ratio measured
                # by a renderer over every text node from one measured over the
                # subset a page chose to mention, and those are not the same
                # claim.
                record["contrast_source"] = source
                if source == SOURCE_DECLARED:
                    record["caveat"] = DECLARED_CAVEAT
            records.append(record)
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
                "contrast_source": source,
                "contrast_note": (
                    "contrast ratios are computed here from the colour pairs "
                    "the snapshot declares, not taken from a self-reported "
                    "claim; an undeclared palette fails the check"
                ) if source == SOURCE_DECLARED else (
                    "contrast ratios are computed here from the foreground and "
                    "background a renderer computed for every text node, and the "
                    "capture is checked against the snapshot's own markup, so a "
                    "pair left out is a text run left unaccounted for"
                ),
                "contrast_caveat": DECLARED_CAVEAT if source == SOURCE_DECLARED else "",
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
