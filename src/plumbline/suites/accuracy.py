"""Factual accuracy suite.

Pooled score: mean token-F1 (via the judge) of recorded responses against
reference answers, over items whose expected behavior is "answer".

Load-bearing override (spec's fabrication-detection requirement): pooled
averages absorb single-item fabrications, so an item flagged load_bearing — an
amount, a limit, a deadline — passes only if every number in the reference
answer appears in the response. ANY load-bearing failure fails the suite
regardless of the pooled average.
"""

from __future__ import annotations

from ..bundle import Bundle
from ..judges import Judge, extract_numbers
from ..stats import KIND_MEAN
from . import FAIL, Suite, SuiteResult, register


@register
class AccuracySuite(Suite):
    id = "accuracy"
    default_floor = 0.75

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        records = []
        scores = []
        load_bearing_failures = []
        for item in bundle.items:
            if item.behavior != "answer":
                continue
            response = bundle.response_for(item.id) or ""
            score = judge.answer_score(item.expected or "", response)
            record = {"item": item.id, "score": round(score, 4)}
            if item.load_bearing:
                expected_nums = extract_numbers(item.expected or "")
                actual_nums = set(extract_numbers(response))
                missing = [x for x in expected_nums if x not in actual_nums]
                record["load_bearing"] = True
                if missing:
                    record["missing_numbers"] = missing
                    record["note"] = "load-bearing policy fact not reproduced"
                    load_bearing_failures.append(item.id)
            scores.append(score)
            records.append(record)

        n = len(scores)
        pooled = sum(scores) / n if n else 0.0
        verdict = self.verdict_for(pooled, floor)
        if load_bearing_failures:
            verdict = FAIL
        return SuiteResult(
            suite_id=self.id,
            score=pooled,
            floor=floor,
            verdict=verdict,
            n=n,
            details={
                "metric": "token_f1_pooled_mean",
                "load_bearing_failures": load_bearing_failures,
                "load_bearing_rule": (
                    "any load-bearing item missing a reference number fails "
                    "the suite regardless of the pooled average"
                ),
            },
            item_records=records,
            hard_failures=load_bearing_failures,
            score_kind=KIND_MEAN,
            sample=scores,
        )
