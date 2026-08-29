#!/usr/bin/env python3
"""WCAG-style structural check on the published evidence page itself.

`src/plumbline/suites/accessibility.py` checks a *target's* interface
snapshot and refuses to publish a verdict about it without doing so. This
script is that same standard turned on this repository's own page,
`site/index.html`: the thing a harness holds targets to and never checks
about itself is a standard that only ever points outward.

Six checks, all structural, all decidable from the page's own markup and
`<style>` block:

1. **Language declaration** — the root element declares a language.
2. **Heading order** — exactly one `h1`, no skipped levels.
3. **Link text** — no link's accessible name is empty or a generic phrase
   ("click here", "read more", ...) that means nothing out of context to
   someone navigating by a links list.
4. **Image alt text** — every `<img>` has an `alt` attribute. Vacuously true
   if the page has no images, the same way `citation_validity` is vacuously
   true for an answer that cites nothing: there is nothing here for the
   check to have caught, which is a different claim from having verified it.
5. **One `<main>` landmark** — a screen reader user can jump straight to the
   content.
6. **Zoom is not disabled** — the viewport meta tag does not set
   `user-scalable=no` or cap `maximum-scale` below 2, either of which blocks
   the 200% reflow WCAG 1.4.4 asks for.

A seventh check, contrast, reuses `contrast_ratio` from the accessibility
suite rather than re-deriving the WCAG relative-luminance formula a second
time — computed, not taken on trust, exactly as that suite insists a
target's declared palette be. The pairs checked are declared in
`CONTRAST_PAIRS` below, by hand, once, against the CSS selector each one
actually belongs to; both the light and the dark palette in the page's own
`:root` blocks are checked, since `color-scheme: light dark` means a visitor
gets whichever one their system prefers.

Structural checks on one page, exhaustively run: a census, not a sample.
There is no confidence interval to report here for the same reason
`accessibility.py`'s docstring gives none for its own five.

    python3 tools/check_site_a11y.py

An eighth, `palette_coverage`, checks that the seventh was asked about
every colour the page declares: `CONTRAST_PAIRS` is a hand-written list, so
without it a colour added later is simply absent from the check and the page
still reports a clean pass. Every declared colour is either in a checked
pair or in `UNCHECKED_PALETTE_VARS` with a reason.

Exit 0 all checks passed, 1 otherwise. Run by `make verify` (folded into
`site-check`) and by `tests/test_site_a11y.py`.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from plumbline.suites.accessibility import AA_NORMAL, contrast_ratio  # noqa: E402

PAGE = REPO / "site" / "index.html"

# (selector this pair belongs to, foreground custom property, background
# custom property). Read by eye from the page's own <style> block and kept
# in sync with it by hand, the same way a bundle's contrast declaration is
# kept in sync with its interface by whoever captures the snapshot.
CONTRAST_PAIRS = [
    ("body, p, li", "fg", "bg"),
    (".lede, .note, footer, th", "muted", "bg"),
    (".kv dt (inside .card)", "muted", "card"),
    ("a", "accent", "bg"),
    ("code, .exit (on --code-bg)", "fg", "code-bg"),
    (".pass (table cell, on --bg)", "ok", "bg"),
    (".pass (inside .card)", "ok", "card"),
    (".stop (table cell, on --bg)", "stop", "bg"),
    (".stop (inside .card)", "stop", "card"),
]

UNCHECKED_PALETTE_VARS = {
    "rule": (
        "a 1px border colour, never used for text or for a control's "
        "boundary that conveys state. WCAG 1.4.11 asks 3:1 of non-text "
        "contrast; this check measures the 4.5:1 text bar, which is the "
        "wrong bar for it. Listed rather than omitted so that the omission "
        "is a decision on the record."
    ),
}
"""Palette colours deliberately outside the contrast check, and why.

`CONTRAST_PAIRS` is written by hand, so on its own it can only prove that
the pairs somebody remembered are sound. It is silent about a colour added
to the palette later and never listed -- the page would grow a new colour,
the check would go on reporting "all 9 declared pairs meet WCAG AA", and
nothing would say that the ninth was not the last one. That is the same
shape as a checksum file that notices an edited entry and not a missing
one, which this repository refuses in `plumbline validate` (a file present
but not listed is an integrity refusal, not a pass).

So every colour the page declares has to be accounted for: checked in a
pair, or named here with a reason. Adding a colour without doing either
fails `palette_coverage`.
"""

GENERIC_LINK_TEXT = {
    "here", "click here", "read more", "more", "link", "click", "this",
}


class _Snapshot(HTMLParser):
    """Collects only what the checks below need."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root_lang: str | None = None
        self.headings: list[int] = []
        self.main_count = 0
        self.images: list[dict] = []
        self.links: list[dict] = []
        self.viewport: str | None = None
        self.style_text = ""
        self._in_style = False
        self._link_stack: list[dict] = []
        self._text_target: dict | None = None

    def handle_starttag(self, tag, attrs):
        attributes = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.root_lang = attributes.get("lang") or None
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.headings.append(int(tag[1]))
        elif tag == "main":
            self.main_count += 1
        elif tag == "img":
            self.images.append(attributes)
        elif tag == "meta" and attributes.get("name") == "viewport":
            self.viewport = attributes.get("content", "")
        elif tag == "style":
            self._in_style = True
        elif tag == "a":
            link = {"href": attributes.get("href"), "text": "",
                    "aria_label": attributes.get("aria-label")}
            self.links.append(link)
            self._link_stack.append(link)

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False
        elif tag == "a" and self._link_stack:
            self._link_stack.pop()

    def handle_data(self, data):
        if self._in_style:
            self.style_text += data
        if self._link_stack:
            self._link_stack[-1]["text"] += data


def _load() -> _Snapshot:
    snapshot = _Snapshot()
    snapshot.feed(PAGE.read_text(encoding="utf-8"))
    snapshot.close()
    return snapshot


def _check_language(snapshot: _Snapshot) -> tuple[bool, str]:
    if snapshot.root_lang:
        return True, f"root element declares lang=\"{snapshot.root_lang}\""
    return False, "the root element declares no language"


def _check_heading_order(snapshot: _Snapshot) -> tuple[bool, str]:
    if not snapshot.headings:
        return False, "the page has no headings"
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


def _check_link_text(snapshot: _Snapshot) -> tuple[bool, str]:
    if not snapshot.links:
        return True, "the page has no links"
    bad = []
    for link in snapshot.links:
        name = (link["aria_label"] or link["text"] or "").strip()
        if not name:
            bad.append(link["href"] or "<no href>")
        elif name.lower() in GENERIC_LINK_TEXT:
            bad.append(f"{link['href']} (text: {name!r})")
    if bad:
        return False, f"links with no name or a generic one: {', '.join(bad)}"
    return True, f"all {len(snapshot.links)} links have a distinct accessible name"


def _check_image_alt(snapshot: _Snapshot) -> tuple[bool, str]:
    if not snapshot.images:
        return True, "the page has no images"
    missing = [img.get("src", "<no src>") for img in snapshot.images
               if "alt" not in img]
    if missing:
        return False, f"images with no alt attribute: {', '.join(missing)}"
    return True, f"all {len(snapshot.images)} images have an alt attribute"


def _check_main_landmark(snapshot: _Snapshot) -> tuple[bool, str]:
    if snapshot.main_count == 1:
        return True, "exactly one <main> landmark"
    if snapshot.main_count == 0:
        return False, "the page has no <main> landmark"
    return False, f"the page has {snapshot.main_count} <main> landmarks, not one"


def _check_zoom_not_disabled(snapshot: _Snapshot) -> tuple[bool, str]:
    if snapshot.viewport is None:
        return False, "no <meta name=\"viewport\"> was found"
    content = snapshot.viewport.replace(" ", "").lower()
    if "user-scalable=no" in content:
        return False, f"viewport disables zoom: {snapshot.viewport!r}"
    for clause in content.split(","):
        if clause.startswith("maximum-scale="):
            try:
                if float(clause.split("=", 1)[1]) < 2:
                    return False, (f"viewport caps zoom below 200%: "
                                   f"{snapshot.viewport!r}")
            except ValueError:
                return False, f"unreadable maximum-scale: {snapshot.viewport!r}"
    return True, f"viewport does not disable zoom: {snapshot.viewport!r}"


def _extract_palette(block: str) -> dict[str, str]:
    """`--name: #hex;` declarations out of one `:root { ... }` block."""
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,8})", block))


def _palettes(snapshot: _Snapshot) -> tuple[dict[str, str], dict[str, str]] | str:
    """Both palettes, or a string saying why they could not be read.

    The dark palette lives inside `@media (prefers-color-scheme: dark)`;
    everything before that keyword is the light (default) palette. One split
    is enough because the page declares exactly one such block.
    """
    if not snapshot.style_text.strip():
        return "the page has no <style> block to check"
    light_text, _, dark_text = snapshot.style_text.partition("@media")
    light = _extract_palette(light_text)
    dark = _extract_palette(dark_text)
    if not light or not dark:
        return ("could not find both a light and a dark palette in "
                "the page's <style> block")
    return light, dark


def _check_palette_coverage(snapshot: _Snapshot) -> tuple[bool, str]:
    """Every colour the page declares is checked, or exempt with a reason.

    Without this, `contrast` proves only that the pairs someone remembered
    to list are sound. A colour added to the palette and never listed is
    invisible to it, and the page reports a clean pass over a bar the new
    colour was never held to.
    """
    palettes = _palettes(snapshot)
    if isinstance(palettes, str):
        return False, palettes
    light, dark = palettes
    if set(light) != set(dark):
        only_light = sorted(set(light) - set(dark))
        only_dark = sorted(set(dark) - set(light))
        return False, (
            "the light and dark palettes declare different colours, so one "
            "theme falls back to the other's value: "
            f"light only {only_light}, dark only {only_dark}")
    declared = set(light)
    covered = {name for _, fg, bg in CONTRAST_PAIRS for name in (fg, bg)}
    unclassified = sorted(declared - covered - set(UNCHECKED_PALETTE_VARS))
    if unclassified:
        return False, (
            "declared in the palette but neither checked for contrast nor "
            f"listed in UNCHECKED_PALETTE_VARS with a reason: {unclassified}")
    stale = sorted(set(UNCHECKED_PALETTE_VARS) - declared)
    if stale:
        return False, (
            "UNCHECKED_PALETTE_VARS exempts colours the page no longer "
            f"declares, so the exemption is stale: {stale}")
    return True, (
        f"all {len(declared)} declared colours are accounted for: "
        f"{len(declared - set(UNCHECKED_PALETTE_VARS))} checked for contrast, "
        f"{len(UNCHECKED_PALETTE_VARS)} exempt with a stated reason")


def _check_contrast(snapshot: _Snapshot) -> tuple[bool, str]:
    palettes = _palettes(snapshot)
    if isinstance(palettes, str):
        return False, palettes
    light, dark = palettes
    failures = []
    for theme_name, palette in (("light", light), ("dark", dark)):
        for selector, fg_name, bg_name in CONTRAST_PAIRS:
            fg, bg = palette.get(fg_name), palette.get(bg_name)
            if not fg or not bg:
                failures.append(
                    f"{theme_name}: --{fg_name} or --{bg_name} is not "
                    f"declared, needed by {selector}")
                continue
            ratio = contrast_ratio(fg, bg)
            if ratio < AA_NORMAL:
                failures.append(
                    f"{theme_name}: {selector} is {ratio:.2f}:1 "
                    f"(--{fg_name} {fg} on --{bg_name} {bg}; needs "
                    f"{AA_NORMAL}:1)")
    if failures:
        return False, "; ".join(failures)
    return True, (f"all {len(CONTRAST_PAIRS)} declared pairs meet WCAG AA "
                  f"({AA_NORMAL}:1) in both the light and dark palette")


CHECKS = (
    ("language_declaration", _check_language),
    ("heading_order", _check_heading_order),
    ("link_text", _check_link_text),
    ("image_alt_text", _check_image_alt),
    ("main_landmark", _check_main_landmark),
    ("zoom_not_disabled", _check_zoom_not_disabled),
    ("contrast", _check_contrast),
    ("palette_coverage", _check_palette_coverage),
)


def run() -> list[tuple[str, bool, str]]:
    snapshot = _load()
    return [(name, *check(snapshot)) for name, check in CHECKS]


def main(argv: list[str] | None = None) -> int:
    del argv
    if not PAGE.is_file():
        print(f"{PAGE.relative_to(REPO)} does not exist; run "
              f"`python3 tools/build_site.py` first", file=sys.stderr)
        return 1
    results = run()
    failed = [(name, detail) for name, passed, detail in results if not passed]
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")
    if failed:
        print(f"\n{len(failed)} of {len(results)} checks failed",
              file=sys.stderr)
        return 1
    print(f"\nall {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
