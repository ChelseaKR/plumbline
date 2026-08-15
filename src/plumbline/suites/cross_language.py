"""Cross-language agreement: the same fact, asked in two languages, must
come back the same.

This is the suite the specification calls first-class fabrication detection,
and it is the one that catches what pooled averages hide. A single wrong
policy number in a modest dataset moves an accuracy mean by a few points and
sails over its floor. But the *pair* is unambiguous: if the English answer
says 900 and the Spanish answer says 850, one of them is invented, and no
amount of averaging makes that acceptable.

The check is deliberately language-independent. Comparing wording across
languages is meaningless for a lexical judge, so each pair is compared on two
signals that survive translation:

1. **Numeric agreement** — the set of numbers in the two responses must match.
   Amounts, limits and deadlines are exactly the facts that carry policy
   weight, and they are written the same way in both languages.
2. **Behavior agreement** — the two responses must both be refusals or both be
   answers. A system that answers a question in English and refuses it in
   Spanish is failing its Spanish speakers, whatever its per-language scores
   look like.

Severity: a numeric disagreement on an item flagged `load_bearing` fails the
suite outright, regardless of the pooled score. That is the "scored harshly"
requirement, and it makes the same severity promise the accuracy suite makes.
"""

from __future__ import annotations

from itertools import combinations

from ..bundle import Bundle
from ..judges import Judge, extract_numbers, strip_citations
from ..stats import KIND_PROPORTION
from . import FAIL, Suite, SuiteResult, register


@register
class CrossLanguageSuite(Suite):
    id = "cross_language"
    # Floor 1.00: two languages disagreeing about the same fact is never
    # acceptable, so there is no fraction of it worth tolerating. Severity
    # handling still distinguishes load-bearing disagreements in the report.
    default_floor = 1.00

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        by_fact: dict[str, list] = {}
        unlinked = []
        for item in bundle.items:
            if item.fact_id:
                by_fact.setdefault(item.fact_id, []).append(item)
            else:
                unlinked.append(item.id)

        pairs = []
        single_language_facts = []
        for fact_id in sorted(by_fact):
            members = sorted(by_fact[fact_id], key=lambda i: i.id)
            if len({i.lang for i in members}) < 2:
                single_language_facts.append(fact_id)
                continue
            for left, right in combinations(members, 2):
                if left.lang != right.lang:
                    pairs.append((fact_id, left, right))

        self.require_population(
            pairs,
            "no fact is asked in two languages (items need a shared `fact_id` "
            "and different `lang` values)",
        )

        records = []
        sample = []
        hard_failures = []
        for fact_id, left, right in pairs:
            left_text = strip_citations(bundle.response_for(left.id) or "")
            right_text = strip_citations(bundle.response_for(right.id) or "")
            left_numbers = sorted(set(extract_numbers(left_text)))
            right_numbers = sorted(set(extract_numbers(right_text)))
            numbers_agree = left_numbers == right_numbers

            left_refused = judge.is_refusal(left_text)
            right_refused = judge.is_refusal(right_text)
            behavior_agrees = left_refused == right_refused

            load_bearing = left.load_bearing or right.load_bearing
            ok = numbers_agree and behavior_agrees
            sample.append(1.0 if ok else 0.0)

            record = {
                "fact": fact_id,
                "pair": [left.id, right.id],
                "languages": [left.lang, right.lang],
                "score": 1.0 if ok else 0.0,
                "numbers": {left.lang: left_numbers, right.lang: right_numbers},
            }
            disagreements = []
            notes = []
            if not numbers_agree:
                disagreements.append("numeric")
                notes.append(
                    f"{left.lang} and {right.lang} report different numbers "
                    f"for the same fact"
                )
                if load_bearing:
                    record["load_bearing"] = True
                    hard_failures.extend([left.id, right.id])
            if not behavior_agrees:
                disagreements.append("behavior")
                record["behavior"] = {
                    left.lang: "refusal" if left_refused else "answer",
                    right.lang: "refusal" if right_refused else "answer",
                }
                answered, refused = ((right.lang, left.lang) if left_refused
                                     else (left.lang, right.lang))
                notes.append(f"answered in {answered} but refused in {refused}")
            if disagreements:
                record["disagreements"] = disagreements
                record["note"] = "; ".join(notes)
            records.append(record)

        n = len(sample)
        score = sum(sample) / n
        verdict = self.verdict_for(score, floor)
        if hard_failures:
            verdict = FAIL

        return SuiteResult(
            suite_id=self.id,
            score=score,
            floor=floor,
            verdict=verdict,
            n=n,
            details={
                "metric": "paired numeric and behavior agreement",
                "facts_compared": sorted({p[0] for p in pairs}),
                "single_language_facts": single_language_facts,
                "items_without_fact_id": unlinked,
                "load_bearing_failures": sorted(set(hard_failures)),
                "severity_rule": (
                    "a numeric disagreement on a load-bearing fact fails this "
                    "suite regardless of the pooled average"
                ),
                "not_compared_note": (
                    "facts present in only one language and items with no "
                    "fact_id are named here rather than silently dropped; "
                    "they are outside this suite's population, not excused "
                    "from it"
                ),
            },
            item_records=records,
            hard_failures=sorted(set(hard_failures)),
            score_kind=KIND_PROPORTION,
            sample=sample,
        )
