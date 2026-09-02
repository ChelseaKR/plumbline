"""Factual accuracy suite.

Pooled score: mean token-F1 (via the judge) of recorded responses against
reference answers, over items whose expected behavior is "answer".

Load-bearing override (spec's fabrication-detection requirement): pooled
averages absorb single-item fabrications, so an item flagged load_bearing — an
amount, a limit, a deadline — passes only if every number in the reference
answer appears in the response. ANY load-bearing failure fails the suite
regardless of the pooled average.

This suite scores a *subset* of the bundle — the items whose expected
behavior is "answer" — and that subset can be empty while the bundle is not:
a safety-probe set is all `refuse`. An empty subset used to score `0.0` over
`n = 0`, which reads in the report as "the target answered everything wrong"
and is a number nothing measured. It is a configuration error instead, the
same one every other suite that narrows its population already raises.
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
        population = self.require_population(
            [i for i in bundle.items if i.behavior == "answer"],
            "no item in it expects the target to answer, so there is no "
            "answer here whose accuracy could be scored",
        )
        records = []
        scores = []
        load_bearing_failures = []
        for item in population:
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

        # `require_population` above already refused an empty population, so
        # there is no `if n else 0.0` here: the only value that fallback could
        # ever have produced was a score for a suite that scored nothing.
        n = len(scores)
        pooled = sum(scores) / n
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
