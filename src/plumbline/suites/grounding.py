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
from ..judges import Judge, asserts_nothing, citations, strip_citations
from ..stats import KIND_MEAN
from . import (
    FAIL,
    SILENCE_NOTE,
    UNVERIFIABLE,
    Suite,
    SuiteResult,
    readable,
    register,
    split_unreadable,
    unreadable_records,
    unverifiable_block,
)

# Reason id: the response is readable but asserts nothing a source could
# support — no content token and no number survive normalization.
NO_CLAIM = "no_claim"

NO_CLAIM_NOTE = (
    "these responses are readable but assert nothing: every word in them is a "
    "function word and there is no number, so the support measure divides by "
    "zero claims and returns a perfect 1.00. `the the of and to` is not a "
    "well-grounded answer, it is an answer with nothing in it to ground. "
    "Excluded from the score and named; `accuracy` and `multilingual` are the "
    "suites that score such a response wrong rather than unverifiable."
)


def _sourced_answer_items(bundle: Bundle):
    """Answer items that had sources available: the population for which
    'was this grounded?' is a meaningful question."""
    return [i for i in bundle.items if i.behavior == "answer" and i.sources]


def _resolved_text(bundle: Bundle, source_id: str) -> str:
    """The text of a source id already known to resolve.

    Every call site filters its candidate ids through `bundle.source(c) is
    not None` before this is ever reached, so the lookup below cannot
    actually return None — but that filtering happens in a different
    comprehension, at a different point in the control flow, which mypy has
    no way to carry forward across. Asking again and refusing loudly if it
    ever really were unresolved is cheaper than a second parallel structure
    just to keep a Source object instead of an id, and consistent with this
    project's own preference for a loud internal error over a silent one.
    """
    source = bundle.source(source_id)
    if source is None:
        raise RuntimeError(
            f"source '{source_id}' resolved once and not again; this is a "
            f"bug in the suite, not in the evidence")
    return source.text


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
        # The same arithmetic covers a response that is readable but asserts
        # nothing — only function words, no numbers — so that is excluded here
        # too rather than scored a perfect 1.00.
        scorable, excluded = split_unreadable(bundle, eligible)
        vacuous = [i.id for i in scorable
                   if asserts_nothing(bundle.response_for(i.id) or "")]
        excluded[NO_CLAIM] = vacuous
        asserted_nothing = set(vacuous)
        population = self.require_population(
            [i for i in scorable if i.id not in asserted_nothing],
            "no answer item's recorded response asserts anything a source "
            "could support, so there is no claim whose grounding could be "
            "checked",
        )
        records = unreadable_records(
            {r: ids for r, ids in excluded.items() if r != NO_CLAIM})
        records.extend({
            "item": item_id,
            "verdict": UNVERIFIABLE,
            "reason": NO_CLAIM,
            "note": ("this response asserts nothing a source could support, so "
                     "support for it is vacuously total; excluded from the "
                     "score, and not a pass"),
        } for item_id in vacuous)
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
                    excluded, eligible=len(eligible),
                    scored=len(population),
                    note=SILENCE_NOTE + " " + NO_CLAIM_NOTE),
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
                if not readable(response):
                    # A response that is nothing but citation markers resolves
                    # every one of them and used to score a perfect 1.0 here.
                    # Citing correctly is a property of an answer, and there is
                    # no answer. Fabricated citations above still count: an
                    # invented reference is an invented reference.
                    score = 0.0
                    record["note"] = (
                        "the response has no readable content beyond its "
                        "citation markers; a citation is not an answer"
                    )
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
            cited_text = "\n".join(_resolved_text(bundle, c) for c in cited)
            score, tokens, numbers, unsupported = _support(
                judge, response, cited_text)
            # An answer that asserts nothing is supported by everything it
            # cites, arithmetically. A response of "[src-rent-cap]" or of
            # "the and of" therefore scored a perfect 1.0 for pointing the
            # reader at a passage it took nothing from. This suite asks whether
            # a real answer's pointer leads anywhere; there is no answer.
            if asserts_nothing(response):
                score, tokens, numbers = 0.0, 0.0, 0.0
            unrelated = [
                c for c in cited
                if judge.support_score(_resolved_text(bundle, c),
                                       strip_citations(response)) == 0.0
            ]
            record = {
                "item": item.id,
                "score": round(score, 4),
                "cited": cited,
                "token_support": round(tokens, 4),
                "number_support": round(numbers, 4),
            }
            if asserts_nothing(response):
                record["asserts_nothing"] = True
            if unsupported:
                record["unsupported_numbers"] = unsupported
            if unrelated:
                record["unrelated_citations"] = unrelated
                record["note"] = (
                    "cited a source with no content in common with the answer"
                )
            if record.get("asserts_nothing"):
                record["note"] = (
                    "the response asserts nothing the cited passages could "
                    "support; scored zero rather than vacuously supported"
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
