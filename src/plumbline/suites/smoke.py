"""Smoke suite: proves the target is testable at all.

Score: fraction of items with a non-empty recorded response. Default floor is
1.00 — a single untestable item means broken plumbing, not a quality signal.
"""

from __future__ import annotations

from ..bundle import Bundle
from ..judges import Judge
from . import Suite, SuiteResult, register


@register
class SmokeSuite(Suite):
    id = "smoke"
    default_floor = 1.00

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        records = []
        covered = 0
        for item in bundle.items:
            response = bundle.response_for(item.id)
            ok = bool(response and response.strip())
            covered += ok
            records.append({
                "item": item.id,
                "score": 1.0 if ok else 0.0,
                "note": "response recorded" if ok else "no recorded response",
            })
        n = len(bundle.items)
        score = covered / n if n else 0.0
        return SuiteResult(
            suite_id=self.id,
            score=score,
            floor=floor,
            verdict=self.verdict_for(score, floor),
            n=n,
            details={"items_with_response": covered, "items_total": n},
            item_records=records,
        )
