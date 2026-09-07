#!/usr/bin/env python3
"""Capture an interface snapshot with the colours a renderer actually computed.

The `accessibility` suite computes WCAG contrast ratios itself, but until now
the colour pairs came from a JSON block the snapshot wrote **about itself**.
The ratios were real; the population was not. A page whose hint text fails AA
could list its five passing pairs and score a clean pass, and nothing in a
markup-only check could notice, because deciding what colour a paragraph is
means running the cascade -- and shipping a cascade implementation inside a
stdlib-only gate was never going to happen.

A browser already has one. This script loads the page in Chromium, walks every
text node, asks the renderer for the computed foreground and the nearest
painted background, and writes the result into the snapshot as a
`plumbline-computed-contrast` block. The suite then measures ratios over what
the page renders rather than over what it says about itself.

**This is an input, not a gate.** It sits in `tools/`, outside the harness and
outside `plumbline gate`, exactly the way a recording does. Playwright is not a
dependency of Plumbline and is not installed by `make install`; the gate imports
nothing from this file, and `tests/test_accessibility.py` holds that open by
asserting no `plumbline.*` module reaches `playwright` in `sys.modules`. Running
the gate on a machine that has never heard of a browser behaves exactly as it
did before.

Usage
-----

    pip install 'playwright==1.49.1' && playwright install chromium
    python3 tools/capture_interface.py https://example.gov/assistant \\
        --out datasets/my-bundle/interface.html

Then re-seal the bundle, because the interface is evidence:

    python3 -m plumbline seal datasets/my-bundle

What the block claims, and what checks it
-----------------------------------------

`source: computed` is a string, and a string is a claim anyone can type. The
suite does not take it at its word: it reads every rendered text run out of the
markup the block sits in and requires the block to account for all of them,
either as a measured pair or as an explicitly skipped node with a stated
reason. A block that lists only its passing pairs is a block that is missing
text, and missing text is visible from the markup alone.

That is why every pair carries the element's own `text`, and why a node the
renderer did not paint -- `display:none`, `visibility:hidden`, a zero-sized box
-- goes into `skipped` with the reason rather than being dropped. Dropping it
silently is indistinguishable from removing a pair that failed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# The JavaScript is the other half of the completeness check, so its text
# normalisation has to be the same rule as `normalise_text` in
# `src/plumbline/suites/accessibility.py`: collapse whitespace runs to one
# space, strip the ends. `tests/test_accessibility.py` holds the two to the
# same fixture -- a check whose two sides normalise differently reports every
# honest snapshot as incomplete, and a check that fails correct input is a
# check somebody switches off.
_MEASURE_JS = r"""
() => {
  const norm = (s) => s.split(/\s+/).filter(Boolean).join(" ");
  const toHex = (value) => {
    const m = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/.exec(value);
    if (!m) return null;
    const alpha = m[4] === undefined ? 1 : parseFloat(m[4]);
    if (alpha === 0) return null;            // fully transparent paints nothing
    const hex = (n) => Number(n).toString(16).padStart(2, "0");
    return { hex: "#" + hex(m[1]) + hex(m[2]) + hex(m[3]), alpha };
  };
  // The nearest ancestor that actually paints a background. A transparent
  // background is not white; it is whatever is behind it, and guessing white
  // is how a dark theme comes out reading as compliant.
  const backgroundOf = (el) => {
    for (let node = el; node; node = node.parentElement) {
      const parsed = toHex(getComputedStyle(node).backgroundColor);
      if (parsed && parsed.alpha === 1) return parsed.hex;
      if (parsed) return null;               // semi-transparent: not decidable here
    }
    const body = toHex(getComputedStyle(document.body).backgroundColor);
    return body ? body.hex : "#ffffff";
  };
  const pairs = [];
  const skipped = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = norm(node.nodeValue || "");
    if (!text) continue;
    const el = node.parentElement;
    if (!el) { skipped.push({ text, reason: "text node with no element parent" }); continue; }
    const tag = el.tagName.toLowerCase();
    if (["script", "style", "template", "noscript", "title"].includes(tag)) continue;
    const style = getComputedStyle(el);
    if (style.display === "none") { skipped.push({ text, reason: "display:none" }); continue; }
    if (style.visibility === "hidden") { skipped.push({ text, reason: "visibility:hidden" }); continue; }
    const box = el.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) {
      skipped.push({ text, reason: "zero-sized box" });
      continue;
    }
    const fg = toHex(style.color);
    const bg = backgroundOf(el);
    if (!fg || !bg) {
      skipped.push({
        text,
        reason: "foreground or background is not an opaque colour this capture can resolve",
      });
      continue;
    }
    const px = parseFloat(style.fontSize) || 16;
    const weight = parseInt(style.fontWeight, 10) || 400;
    // WCAG "large text": 18pt (24px), or 14pt (18.66px) bold.
    const large = px >= 24 || (px >= 18.66 && weight >= 700);
    pairs.push({
      name: tag + (el.id ? "#" + el.id : ""),
      text,
      foreground: fg.hex,
      background: bg,
      size: large ? "large" : "normal",
      font_size_px: Math.round(px * 100) / 100,
      font_weight: weight,
    });
  }
  return { pairs, skipped, html: document.documentElement.outerHTML };
}
"""

_BLOCK_RE = re.compile(
    r'<script[^>]*\bid="plumbline-computed-contrast"[^>]*>.*?</script>\s*',
    re.DOTALL | re.IGNORECASE,
)


def render_block(measured: dict[str, object], url: str, tool: str) -> str:
    """The `<script>` block the suite reads, as bytes, deterministically."""
    payload = {
        "source": "computed",
        "tool": tool,
        "url": url,
        "pairs": measured["pairs"],
        "skipped": measured["skipped"],
    }
    body = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        '<script type="application/json" id="plumbline-computed-contrast">\n'
        f"{body}\n"
        "</script>\n"
    )


def insert_block(html: str, block: str) -> str:
    """Put the block in `<head>`, replacing any block a previous run left.

    Replacing rather than appending is not tidiness. Two blocks with the same
    id would leave the suite reading whichever the parser saw last, and a
    re-capture that fixed a failing pair would sit in the same file as the
    capture that found it.
    """
    html = _BLOCK_RE.sub("", html)
    lowered = html.lower()
    index = lowered.find("</head>")
    if index == -1:
        raise SystemExit(
            "capture_interface: the page has no </head> to put the computed "
            "block in; the snapshot was not written"
        )
    return html[:index] + block + html[index:]


def capture(url: str, *, timeout_ms: int) -> tuple[str, dict[str, object], str]:
    """`(html, measured, tool)` from a real browser. Imported lazily on purpose."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise SystemExit(
            "capture_interface: playwright is not installed. It is deliberately "
            "not a dependency of Plumbline -- the gate runs on the standard "
            "library alone. Install it just for this capture:\n"
            "    pip install 'playwright==1.49.1' && playwright install chromium"
        ) from exc
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            tool = f"playwright/chromium {browser.version}"
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            measured = page.evaluate(_MEASURE_JS)
        finally:
            browser.close()
    html = str(measured.pop("html"))
    return html, measured, tool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="The interface to load and measure.")
    parser.add_argument("--out", required=True, type=Path,
                        help="Where to write the snapshot HTML.")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args(argv)

    html, measured, tool = capture(args.url, timeout_ms=args.timeout_ms)
    if not measured["pairs"]:
        # A capture that measured nothing is not a page with nothing to
        # measure. Writing an empty block would put a `source: computed`
        # marker on a file nobody measured, and the suite would then be
        # refusing a snapshot for a reason no reader could trace back to here.
        raise SystemExit(
            f"capture_interface: measured no text at {args.url}. Nothing was "
            f"written. A snapshot with an empty computed block is not evidence "
            f"of good contrast; it is evidence the capture did not run."
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        insert_block(html, render_block(measured, args.url, tool)), encoding="utf-8")
    print(f"{args.out}: {len(measured['pairs'])} measured pairs, "
          f"{len(measured['skipped'])} nodes the renderer did not paint")
    print("The interface is evidence: re-seal the bundle "
          "(`python3 -m plumbline seal <bundle>`) before auditing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
