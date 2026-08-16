"""Grounding: three suites that ask three different questions about the same
answer, because a system can get any two of them right and still mislead.

- **`groundedness`** — is the answer supported by the sources the item had
  available, cited or not? Catches invention.
- **`citation_validity`** — do the sources the answer cites actually exist?
  Catches fabricated references, which no amount of fluent prose reveals.
- **`citation_accuracy`** — do the sources it cited support what it said?
  Catches an answer that is grounded in source B while pointing the reader at
  source A. That reader will check A, find nothing, and lose trust in the
  whole system.

All three use the deterministic lexical judge: content-token recall for word
support, plus a separate check that every number in the answer appears in the
sources. Numbers are treated separately because they survive paraphrase and
translation, and because an unsupported number is the exact shape of the
fabrication this harness exists to catch.

Support is scored as the **weaker** of the two channels, not their average. An
answer whose prose matches a source but whose amount does not is not
three-quarters grounded; it is wrong in the way that matters.
"""

from __future__ import annotations

from ..bundle import Bundle
from ..judges import Judge, citations, strip_citations
from ..stats import KIND_MEAN
from . import (
    FAIL,
    SILENCE_NOTE,
    SILENT,
    Suite,
    SuiteResult,
    register,
    responded,
    silence_record,
    unverifiable_block,
)


def _sourced_answer_items(bundle: Bundle):
    """Answer items that had sources available: the population for which
    'was this grounded?' is a meaningful question."""
    return [i for i in bundle.items if i.behavior == "answer" and i.sources]


def _support(judge: Judge, response: str, source_text: str
             ) -> tuple[float, float, float, list[str]]:
    """(combined, token_support, number_support, unsupported_numbers)."""
    tokens = judge.support_score(response, source_text)
    numbers, unsupported = judge.number_support(response, source_text)
    return min(tokens, numbers), tokens, numbers, unsupported


@register
class GroundednessSuite(Suite):
    id = "groundedness"
    # Content-token recall punishes legitimate paraphrase the same way
    # token-F1 does in the accuracy suite, so a near-perfect floor would be
    # dishonest for a lexical judge. 0.70 still fails an answer that has
    # wandered away from its sources. A demonstration default.
    default_floor = 0.70

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        eligible = self.require_population(
            _sourced_answer_items(bundle),
            "no answer item declares any sources, so there is nothing to be "
            "grounded in",
        )
        # An empty response asserts nothing, so nothing in it is unsupported,
        # so the support measure returns a perfect 1.0. That is arithmetic, not
        # evidence: a target that said nothing is not a well-grounded target.
        silent = [i.id for i in eligible if not responded(bundle, i)]
        population = self.require_population(
            [i for i in eligible if responded(bundle, i)],
            "every answer item's recorded response is empty, so there is no "
            "claim whose grounding could be checked",
        )
        records = [silence_record(i) for i in silent]
        sample, hard_failures = [], []
        for item in population:
            response = bundle.response_for(item.id) or ""
            source_text = bundle.source_text_for(item)
            score, tokens, numbers, unsupported = _support(
                judge, response, source_text)
            record = {
                "item": item.id,
                "score": round(score, 4),
                "token_support": round(tokens, 4),
                "number_support": round(numbers, 4),
                "sources": list(item.sources),
            }
            if unsupported:
                record["unsupported_numbers"] = unsupported
                record["note"] = (
                    "the answer states numbers that appear in none of its "
                    "sources"
                )
                if item.load_bearing:
                    record["load_bearing"] = True
                    hard_failures.append(item.id)
            sample.append(score)
            records.append(record)

        score = sum(sample) / len(sample)
        verdict = FAIL if hard_failures else self.verdict_for(score, floor)
        return SuiteResult(
            suite_id=self.id,
            score=score,
            floor=floor,
            verdict=verdict,
            n=len(sample),
            details={
                "metric": "min(content-token recall, number support) against "
                          "every source available to the item",
                "load_bearing_failures": hard_failures,
                "severity_rule": (
                    "a load-bearing answer stating a number that appears in "
                    "none of its sources fails this suite regardless of the "
                    "pooled average"
                ),
                "items_without_sources": [
                    i.id for i in bundle.items
                    if i.behavior == "answer" and not i.sources
                ],
                "unverifiable": unverifiable_block(
                    {SILENT: silent}, eligible=len(eligible),
                    scored=len(population), note=SILENCE_NOTE),
            },
            item_records=records,
            hard_failures=hard_failures,
            score_kind=KIND_MEAN,
            sample=sample,
        )


@register
class CitationValiditySuite(Suite):
    id = "citation_validity"
    default_floor = 0.95

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        population = self.require_population(
            _sourced_answer_items(bundle),
            "no answer item declares any sources, so no answer was expected "
            "to cite one",
        )
        records, sample, hard_failures = [], [], []
        for item in population:
            response = bundle.response_for(item.id) or ""
            cited = citations(response)
            record = {"item": item.id, "cited": cited}
            if not cited:
                score = 0.0
                record["note"] = (
                    "answer cites nothing although sources were available"
                )
            else:
                fabricated = [c for c in cited if bundle.source(c) is None]
                out_of_context = [
                    c for c in cited
                    if bundle.source(c) is not None and c not in item.sources
                ]
                score = (len(cited) - len(fabricated)) / len(cited)
                if fabricated:
                    record["fabricated_citations"] = fabricated
                    record["note"] = "cites sources that do not exist"
                    hard_failures.append(item.id)
                if out_of_context:
                    record["out_of_context_citations"] = out_of_context
            record["score"] = round(score, 4)
            sample.append(score)
            records.append(record)

        score = sum(sample) / len(sample)
        verdict = FAIL if hard_failures else self.verdict_for(score, floor)
        return SuiteResult(
            suite_id=self.id,
            score=score,
            floor=floor,
            verdict=verdict,
            n=len(sample),
            details={
                "metric": "fraction of inline citations that resolve to a "
                          "source in the corpus; an answer that cites nothing "
                          "scores zero",
                "fabricated_citation_failures": hard_failures,
                "severity_rule": (
                    "citing a source that does not exist fails this suite "
                    "regardless of the pooled average: inventing a reference "
                    "is categorically different from imprecise wording"
                ),
                "out_of_context_note": (
                    "a citation that resolves to the corpus but was not among "
                    "the item's retrieved sources counts as valid and is "
                    "listed per item, because it is a retrieval question, not "
                    "an honesty one"
                ),
            },
            item_records=records,
            hard_failures=hard_failures,
            score_kind=KIND_MEAN,
            sample=sample,
        )


@register
class CitationAccuracySuite(Suite):
    id = "citation_accuracy"
    default_floor = 0.80

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        candidates = _sourced_answer_items(bundle)
        uncited = []
        population = []
        for item in candidates:
            response = bundle.response_for(item.id) or ""
            resolvable = [c for c in citations(response)
                          if bundle.source(c) is not None]
            if resolvable:
                population.append((item, response, resolvable))
            else:
                uncited.append(item.id)
        self.require_population(
            population,
            "no answer resolves a single citation, so there is nothing whose "
            "accuracy could be checked (citation_validity is the suite that "
            "scores that absence)",
        )

        records, sample = [], []
        for item, response, cited in population:
            cited_text = "\n".join(bundle.source(c).text for c in cited)
            score, tokens, numbers, unsupported = _support(
                judge, response, cited_text)
            unrelated = [
                c for c in cited
                if judge.support_score(bundle.source(c).text,
                                       strip_citations(response)) == 0.0
            ]
            record = {
                "item": item.id,
                "score": round(score, 4),
                "cited": cited,
                "token_support": round(tokens, 4),
                "number_support": round(numbers, 4),
            }
            if unsupported:
                record["unsupported_numbers"] = unsupported
            if unrelated:
                record["unrelated_citations"] = unrelated
                record["note"] = (
                    "cited a source with no content in common with the answer"
                )
            sample.append(score)
            records.append(record)

        score = sum(sample) / len(sample)
        return SuiteResult(
            suite_id=self.id,
            score=score,
            floor=floor,
            verdict=self.verdict_for(score, floor),
            n=len(sample),
            details={
                "metric": "min(content-token recall, number support) against "
                          "only the sources the answer actually cited",
                "answers_citing_nothing_resolvable": uncited,
                "scope_note": (
                    "numeric fabrication is owned by the groundedness suite, "
                    "which checks against every available source; this suite "
                    "asks the narrower question of whether the pointer the "
                    "reader was handed leads anywhere useful"
                ),
            },
            item_records=records,
            score_kind=KIND_MEAN,
            sample=sample,
        )
