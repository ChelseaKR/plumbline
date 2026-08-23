"""Passage attribution: did the answer come from the passage that answers the
question?

The gap this exists to close was reported by a consumer, not found here. Their
grounded-answering engine returned an answer about eligibility composed from
the **fare paragraph of the right document**, which shares a word with the
question. It was fluent, drawn from a real passage, cited to that passage, in
the right language, and not a refusal — and every suite passed it, each of
them answering its own question correctly:

- `groundedness` scores support against the union of the item's sources, and
  the fare paragraph was one of them.
- `citation_validity` resolves the cited id, which exists.
- `citation_accuracy` asks whether the cited passage supports the answer. It
  does, completely: that is where the answer came from. The suite is strongest
  exactly where the defect is worst.
- `accuracy` sees one item's token-F1 fall into a pooled mean. It cannot say
  *wrong paragraph*, only *less similar to the reference than average*, and a
  floor set honestly for a lexical judge leaves room for paraphrase — which is
  the room this defect hides in.

So this suite asks the one question none of them asks: of the passages this
item had, which one best accounts for the answer, and is it one that actually
answers the question?

**Only the item can say which passage answers it.** A lexical judge can
compare passages; it cannot read a question. Inferring the answering passage
from the reference answer is often right, unsound, and silent when it is
wrong, so it is not used for scoring here (see `suggested_declarations`, which
is a prompt for a human and never a score). An item that declares nothing is
reported UNVERIFIABLE, never passed: a vacuous pass would put a green tick on
precisely the property nobody was checking.

The rule, per item that declares `answering_sources`:

- *a* = the best content-token recall of the response against any single
  declared answering passage;
- *d* = the same against any single other passage the item had (a distractor);
- **pass** when `a - d >= DECISION_MARGIN`, **fail** when
  `d - a >= DECISION_MARGIN`, **UNVERIFIABLE** in between, because a
  comparison that close is one this instrument cannot make.

Comparative, not thresholded: the stopword list, the paraphrase penalty and
the normalizer's quirks apply to both sides and largely cancel. That is the
part a lexical judge can do well.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..bundle import Bundle, Item, Source
from ..judges import Judge, citations
from ..stats import KIND_PROPORTION
from . import (
    FAIL,
    SILENT,
    UNREADABLE,
    UNVERIFIABLE,
    Suite,
    SuiteResult,
    register,
    unreadable_reason,
    unverifiable_block,
)

# How much better one passage must account for an answer before this suite
# will name it. Chosen here, arbitrary like every other constant in this
# repository; the band below it is the honesty margin, not a tolerance.
DECISION_MARGIN = 0.10

NO_DECLARATION = "no_declaration"
NO_DISTRACTOR = "no_distractor"
INDISTINGUISHABLE = "indistinguishable"


def _best(judge: Judge, text: str, passages: list[Source]) -> tuple[float, str]:
    """(support, id) of the passage that best accounts for `text`.

    Ties resolve to the lexically first id so the report is reproducible.
    """
    ranked = sorted(
        ((judge.support_score(text, passage.text), passage.id)
         for passage in passages),
        key=lambda pair: (-pair[0], pair[1]),
    )
    return ranked[0]


@register
class PassageAttributionSuite(Suite):
    id = "passage_attribution"
    # Scored items are the unambiguous ones — the close calls are held out as
    # unverifiable rather than guessed — so a scored failure is an answer
    # materially better accounted for by a passage that does not answer the
    # question. There is very little of that worth tolerating, and the
    # load-bearing override takes the cases where there is none. A
    # demonstration default; per-target config is the real authority.
    default_floor = 0.95

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        eligible = self.require_population(
            [i for i in bundle.items if i.behavior == "answer" and i.sources],
            "no answer item declares any sources, so no answer could have come "
            "from the wrong one",
        )
        declared = self.require_population(
            [i for i in eligible if i.answering_sources],
            "no item declares `answering_sources`, so nothing in this bundle "
            "says which passage was supposed to answer it. Only the dataset "
            "can say that; a lexical judge cannot read a question",
        )

        reasons: dict[str, list[str]] = {
            NO_DECLARATION: [i.id for i in eligible if not i.answering_sources],
            NO_DISTRACTOR: [],
            INDISTINGUISHABLE: [],
            SILENT: [],
            UNREADABLE: [],
        }
        records: list[dict[str, Any]] = []
        sample: list[float] = []
        misattributed: list[str] = []
        hard_failures: list[str] = []
        not_retrieved: list[str] = []

        for item in declared:
            response = bundle.response_for(item.id) or ""
            # An unreadable response is accounted for equally badly by every
            # passage, so both sides of the comparison come out at the support
            # measure's vacuous 1.0 and the margin is zero. That would be
            # reported as `indistinguishable`, which reads as "two plausible
            # passages" when the truth is "no answer". Name it for what it is.
            unreadable = unreadable_reason(bundle, item)
            if unreadable is not None:
                reasons[unreadable].append(item.id)
                records.append({
                    "item": item.id,
                    "answering_sources": list(item.answering_sources),
                    "verdict": UNVERIFIABLE,
                    "reason": unreadable,
                    "note": ("nothing readable was recorded for this item, so "
                             "no passage accounts for it; excluded from the "
                             "score, and not a pass"),
                })
                continue
            answering = bundle.answering_sources_for(item)
            distractors = bundle.distractor_sources_for(item)
            support, best_answering = _best(judge, response, answering)
            cited = citations(response)

            record = {
                "item": item.id,
                "answering_sources": list(item.answering_sources),
                "best_answering_source": best_answering,
                "answering_support": round(support, 4),
                "cited": cited,
            }
            missing = [s for s in item.answering_sources if s not in item.sources]
            if missing:
                not_retrieved.append(item.id)
                record["answering_passage_not_available"] = missing
                # Its own key: the attribution outcome writes `note`, and a
                # reader needs both sentences, not whichever was written last.
                record["retrieval_note"] = (
                    "the passage that answers this question was not among the "
                    "ones the item had: a retrieval failure, not a composition "
                    "one"
                )

            if not distractors:
                record["verdict"] = UNVERIFIABLE
                record["reason"] = NO_DISTRACTOR
                record["note"] = (
                    "this item had only the passage that answers it, so there "
                    "is no wrong paragraph the answer could have come from; a "
                    "pass here would be vacuous"
                )
                reasons[NO_DISTRACTOR].append(item.id)
                records.append(record)
                continue

            other, best_other = _best(judge, response, distractors)
            margin = support - other
            record["best_other_source"] = best_other
            record["other_support"] = round(other, 4)
            record["margin"] = round(margin, 4)

            if margin >= DECISION_MARGIN:
                record["verdict"] = "PASS"
                record["score"] = 1.0
                sample.append(1.0)
                if cited and not any(c in item.answering_sources for c in cited):
                    record["note"] = (
                        "the answer came from a passage that answers the "
                        "question but points the reader at a different one"
                    )
            elif -margin >= DECISION_MARGIN:
                record["verdict"] = FAIL
                record["score"] = 0.0
                record["note"] = (
                    f"the answer is better accounted for by `{best_other}`, "
                    f"which this item does not declare as answering the "
                    f"question: right document, wrong paragraph"
                )
                sample.append(0.0)
                misattributed.append(item.id)
                if item.load_bearing:
                    record["load_bearing"] = True
                    hard_failures.append(item.id)
            else:
                record["verdict"] = UNVERIFIABLE
                record["reason"] = INDISTINGUISHABLE
                record["note"] = (
                    f"`{best_answering}` and `{best_other}` account for this "
                    f"answer within {DECISION_MARGIN} of each other, which is "
                    f"a comparison a lexical judge cannot make"
                )
                reasons[INDISTINGUISHABLE].append(item.id)
            records.append(record)

        scored = len(sample)
        if not scored:
            # Everything declared turned out to be uncheckable. Reporting a
            # score over nothing is the vacuous pass this suite exists to
            # refuse, so it fails closed like any other empty population.
            self.require_population(
                [],
                "every item that declares `answering_sources` is unverifiable "
                "(" + ", ".join(f"{reason}: {len(ids)}"
                                for reason, ids in sorted(reasons.items())
                                if ids and reason != NO_DECLARATION)
                + "), so there is nothing this suite could score",
            )

        score = sum(sample) / scored
        verdict = FAIL if hard_failures else self.verdict_for(score, floor)
        return SuiteResult(
            suite_id=self.id,
            score=score,
            floor=floor,
            verdict=verdict,
            n=scored,
            details={
                "metric": (
                    "fraction of declared items whose answer is best accounted "
                    "for by a passage the item declares as answering the "
                    "question, rather than by another passage it had"
                ),
                "decision_margin": DECISION_MARGIN,
                "misattributed_items": sorted(misattributed),
                "answering_passage_not_available": sorted(not_retrieved),
                "load_bearing_failures": sorted(hard_failures),
                "severity_rule": (
                    "a load-bearing item composed from a passage that does not "
                    "answer the question fails this suite regardless of the "
                    "pooled average: an amount taken from the wrong paragraph "
                    "is a wrong policy fact"
                ),
                "unverifiable": unverifiable_block(
                    reasons, eligible=len(eligible), scored=scored,
                    note=(
                        "an unverifiable item is excluded from the score and "
                        "never counted as a pass. `no_declaration`: the item "
                        "does not say which passage answers it, and only the "
                        "dataset can. `no_distractor`: the item had nothing "
                        "else the answer could have come from. "
                        "`indistinguishable`: two passages account for the "
                        "answer within the decision margin. `silent` / "
                        "`unreadable`: nothing was recorded for the item, or "
                        "nothing in what was recorded survives normalization, "
                        "so no passage accounts for it"
                    ),
                ),
                "suggested_declarations": self._suggestions(bundle, judge, eligible),
                "suggested_declarations_note": (
                    "computed from the reference answer, not from the "
                    "response, and NOT scored: a suggestion is where a human "
                    "should look, not a declaration. Adopting one without "
                    "checking it would have this suite grading answers against "
                    "an expectation it invented"
                ),
                "what_this_cannot_determine": (
                    "whether a declaration is the right one (it is "
                    "human-authored ground truth), anything about an item that "
                    "declares nothing, and whether the answer is correct — an "
                    "answer copied from the passage that answers the question "
                    "scores 1.0 here even when the answer is wrong, which is "
                    "the accuracy suite's question"
                ),
            },
            item_records=records,
            hard_failures=hard_failures,
            score_kind=KIND_PROPORTION,
            sample=sample,
        )

    def _suggestions(self, bundle: Bundle, judge: Judge,
                     eligible: Iterable[Item]) -> dict[str, str]:
        """Where a dataset author should look first, for items that declare
        nothing.

        Only for items with more than one candidate passage — with one, there
        is no wrong paragraph to find — and only when one passage accounts for
        the *reference answer* better than the runner-up by the decision
        margin. Anything closer is a guess, and this file does not guess.
        """
        suggestions: dict[str, str] = {}
        for item in eligible:
            if item.answering_sources:
                continue
            candidates = bundle.sources_for(item)
            if len(candidates) < 2 or not item.expected:
                continue
            ranked = sorted(
                ((judge.support_score(item.expected, c.text), c.id)
                 for c in candidates),
                key=lambda pair: (-pair[0], pair[1]),
            )
            if ranked[0][0] - ranked[1][0] >= DECISION_MARGIN:
                suggestions[item.id] = ranked[0][1]
        return suggestions
