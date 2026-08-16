"""Smoke suite: proves the target is testable at all.

Score: fraction of items whose recorded response has something in it a check
can read. Default floor is 1.00 — a single untestable item means broken
plumbing, not a quality signal.

"Something a check can read" and not "a non-empty string": this suite is the
one every other suite points at when it excludes an item, so if it accepts a
full stop, a zero-width space or a bare citation marker as a response, the
harness has no suite that fails on them and the whole no-silent-pass argument
comes apart. See `readable` in this package's `__init__`.
"""

from __future__ import annotations

from ..bundle import Bundle
from ..judges import Judge
from ..stats import KIND_PROPORTION
from . import SILENT, Suite, SuiteResult, register, unreadable_reason


@register
class SmokeSuite(Suite):
    id = "smoke"
    default_floor = 1.00

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        records = []
        sample = []
        covered = 0
        silent, unreadable = [], []
        for item in bundle.items:
            reason = unreadable_reason(bundle, item)
            ok = reason is None
            covered += ok
            sample.append(1.0 if ok else 0.0)
            if reason == SILENT:
                silent.append(item.id)
                note = "no recorded response"
            elif reason is not None:
                unreadable.append(item.id)
                note = ("a response with no readable content: every character "
                        "in it disappears under normalization")
            else:
                note = "response recorded"
            records.append({
                "item": item.id,
                "score": 1.0 if ok else 0.0,
                "note": note,
            })
        n = len(bundle.items)
        score = covered / n if n else 0.0
        return SuiteResult(
            suite_id=self.id,
            score=score,
            floor=floor,
            verdict=self.verdict_for(score, floor),
            n=n,
            details={
                "items_with_response": covered,
                "items_total": n,
                "silent_items": silent,
                "unreadable_items": unreadable,
                "readability_rule": (
                    "a response counts only if something in it survives "
                    "normalization. Punctuation, emoji, zero-width characters "
                    "and bare citation markers are not responses: they are "
                    "silence that gets past a `.strip()`"
                ),
            },
            item_records=records,
            score_kind=KIND_PROPORTION,
            sample=sample,
        )
