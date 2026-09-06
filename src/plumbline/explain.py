"""One item, across every suite that read it.

`report.json` already holds a record per item per suite, and the coupling disclosure is
computed from those records. A person who sees `rent-cap-en-formal` in three red rows still
has to read JSON to learn why the three are red, and whether they are three problems or one.

This assembles the answer from what the run already wrote down. It re-scores nothing: every
number here was produced by the suite that owns it, and the only computation this module does
is over the item's own text, to say which tokens and which numbers separate the answer from
`expected`. That is the comparison `accuracy` is scored on, and it is the one thing a reader
cannot reconstruct from the record, because the record keeps the score and not the words.

Two consequences of "no re-scoring" worth stating, because both look like omissions:

Denial markers are not recomputed. A `forbidden_claims` hit is reported exactly as the
`conduct` suites recorded it, together with the clauses the item declared, so a reader can see
which declared claim was asserted and which was not. Deciding again whether a claim was denied
would mean running a judge, and under a model judge that is neither offline nor deterministic
-- the two properties that make reading the report worth doing at all.

The language identification decision is reported as the suites recorded it, `asked_in` and
`answered_in`. The script and word counts behind it are not retained in the report, and this
module says so rather than printing a zero that would read as a measurement.

Determinism: suites are emitted in sorted order, records in the order the suite wrote them,
and nothing here reads a clock. Identical inputs produce identical bytes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .bundle import Bundle, IntegrityError, Item
from .judges import extract_numbers, normalize, strip_citations

#: A record belongs to `item_id` when it names it. Most suites key a record by `item`;
#: `cross_language` scores a pair of items and names both under `pair`. Anything else is a
#: record about something that is not an item (an `accessibility` check, say), and is not
#: reachable from an item id at all.
_ITEM_KEYS = ("item", "pair")

#: The metric a suite publishes when its score IS the token comparison against `expected`.
#: The diff this module computes is rendered inside that suite's section, because that is the
#: suite it explains; it is matched on the published metric rather than on the suite's name, so
#: renaming the suite carries the diff with it. A suite that stops publishing this metric loses
#: the diff visibly -- `render_markdown` says the comparison is no longer this suite's -- rather
#: than quietly rendering a section with nothing in it.
_EXPECTED_COMPARISON_METRIC = "token_f1_pooled_mean"

#: How close a suite's pooled score must sit to the mean of its own records before this
#: module will describe an item's share of it. `report.json` rounds scores to four places.
_MEAN_TOLERANCE = 5e-4


class ExplainError(Exception):
    """This report does not describe the item asked about."""


@dataclass(frozen=True)
class SuiteView:
    """What one suite recorded about one item."""

    suite: str
    suite_score: float
    floor: float
    suite_verdict: str
    n: int
    matched_on: str
    metric: str | None
    records: tuple[dict[str, Any], ...]
    hard_failure: bool
    contribution: float | None
    contribution_note: str


def _matches(record: dict[str, Any], item_id: str) -> str | None:
    """Which key made this record this item's, or None."""
    for key in _ITEM_KEYS:
        value = record.get(key)
        if value == item_id:
            return key
        if isinstance(value, list) and item_id in value:
            return key
    return None


def _contribution(suite: dict[str, Any], records: tuple[dict[str, Any], ...]
                  ) -> tuple[float | None, str]:
    """This item's share of the suite's pooled score, when the pooled score is that mean.

    Derived rather than assumed. A suite whose score is a between-group comparison, or one
    that pools over pairs rather than items, has no per-item share, and saying "1/n of the
    score" about it would be a number with no referent. So the mean of the records is
    recomputed and compared against the score the suite published; the share is offered only
    when they agree.
    """
    scored = [r["score"] for r in suite.get("items", [])
              if isinstance(r.get("score"), (int, float))]
    if not scored:
        return None, "this suite recorded no scored items"
    mean = sum(scored) / len(scored)
    if abs(mean - float(suite["score"])) > _MEAN_TOLERANCE:
        return None, (
            f"this suite's score is not the mean of its per-item scores "
            f"(mean {mean:.4f} against a published {float(suite['score']):.4f}), so this "
            f"item has no simple share of it"
        )
    mine = [r["score"] for r in records if isinstance(r.get("score"), (int, float))]
    if not mine:
        return None, "this item has no score in this suite"
    return sum(mine) / len(scored), (
        f"the suite's score is the mean of {len(scored)} per-item scores"
    )


def suite_views(report: dict[str, Any], item_id: str) -> tuple[SuiteView, ...]:
    """Every suite that read this item, in sorted order."""
    views: list[SuiteView] = []
    for suite in sorted(report.get("suites", []), key=lambda s: str(s["suite"])):
        matched: list[dict[str, Any]] = []
        matched_on = ""
        for record in suite.get("items", []):
            key = _matches(record, item_id)
            if key:
                matched.append(record)
                matched_on = matched_on or key
        if not matched:
            continue
        records = tuple(matched)
        contribution, note = _contribution(suite, records)
        views.append(
            SuiteView(
                suite=str(suite["suite"]),
                suite_score=float(suite["score"]),
                floor=float(suite["floor"]),
                suite_verdict=str(suite["verdict"]),
                n=int(suite["n"]),
                matched_on=matched_on,
                metric=(suite.get("details") or {}).get("metric"),
                records=records,
                hard_failure=item_id in (suite.get("hard_failures") or []),
                contribution=contribution,
                contribution_note=note,
            )
        )
    return tuple(views)


def coupling_lines(report: dict[str, Any], item_id: str) -> tuple[str, ...]:
    """The coupling entries that name this item, so two red rows are not read as two findings.

    The couplings block is computed by the run from its own per-item records. This selects the
    entries whose `shared_items` name this item and quotes the run's own reading of them; it
    recomputes nothing, and it never decides on its own that two failures are one.
    """
    couplings = report.get("couplings") or {}
    lines: list[str] = []
    for entry in couplings.get("shared_inputs", []) or []:
        shared = entry.get("shared_items") or []
        if not isinstance(shared, list) or item_id not in shared:
            continue
        suites = ", ".join(entry.get("suites", []))
        failed = entry.get("failed") or []
        reading = entry.get("reading")
        lines.append(
            f"{entry.get('id', 'shared input')}: {suites} share "
            f"{entry.get('shared_input', 'an input')}, and this item is among the "
            f"{entry.get('shared_items_are', 'shared items')}. "
            f"Failed here: {', '.join(failed) if failed else 'none'}. "
            + (str(reading) if isinstance(reading, str) else "")
        )
    return tuple(sorted(lines))


def _diff_against_expected(item: Item, response: str) -> dict[str, Any]:
    """Which tokens and numbers separate the answer from `expected`.

    The one thing this module computes, because the record keeps the score and not the words.

    It is computed the way the suite computes it, not the way that reads best. `answer_score`
    compares `normalize(expected).split()` against `normalize(strip_citations(actual)).split()`
    -- citation markers stripped from the answer, function words kept -- and the load-bearing
    number check compares `extract_numbers` over both sides with the markers left in. A diff
    built any other way is a second opinion wearing the first one's clothes: an earlier draft
    of this function dropped stopwords and kept citations, and reported `src` as a word the
    answer had added, which is a token the score never saw.

    An item with no `expected` is reported as having none. It is not reported as a perfect or
    an empty diff: a comparison that could not be made is not a comparison that came out even.
    """
    if item.expected is None:
        return {"available": False,
                "reason": "this item declares no `expected`, so there is nothing to diff against"}
    expected_tokens = normalize(item.expected).split()
    answer_tokens = normalize(strip_citations(response)).split()
    expected_set, answer_set = set(expected_tokens), set(answer_tokens)
    expected_numbers = extract_numbers(item.expected)
    answer_numbers = extract_numbers(response)
    return {
        "available": True,
        "expected": item.expected,
        "answer": response,
        "tokenisation": "as `answer_score` tokenises: citations stripped from the answer, "
                        "function words kept",
        "missing_tokens": sorted(expected_set - answer_set),
        "added_tokens": sorted(answer_set - expected_set),
        "shared_tokens": len(expected_set & answer_set),
        "missing_numbers": [n for n in expected_numbers if n not in set(answer_numbers)],
        "added_numbers": [n for n in answer_numbers if n not in set(expected_numbers)],
    }


def _passages(bundle: Bundle, item: Item) -> list[dict[str, Any]]:
    answering = set(item.answering_sources)
    passages: list[dict[str, Any]] = []
    for source_id in item.sources:
        source = bundle.source(source_id)
        passages.append({
            "id": source_id,
            "answering_source": source_id in answering,
            "retrieved": source is not None,
            "text": source.text if source is not None else None,
        })
    for source_id in sorted(answering - set(item.sources)):
        # An answering passage the target never retrieved. Named, rather than dropped:
        # `passage_attribution` treats it as a retrieval failure, and a reader comparing
        # this list against the item's declaration would otherwise not see it at all.
        source = bundle.source(source_id)
        passages.append({
            "id": source_id,
            "answering_source": True,
            "retrieved": False,
            "not_among_retrieved": True,
            "text": source.text if source is not None else None,
        })
    return passages


def bundle_view(bundle: Bundle | None, report: dict[str, Any], item_id: str) -> dict[str, Any]:
    """What the bundle says about this item, or why it is not being shown.

    A bundle whose dataset digest is not the one the report names is refused rather than read.
    Explaining an item against a different dataset would produce a fluent account of an answer
    the run never scored, which is the failure this project exists to make impossible.
    """
    if bundle is None:
        return {"available": False,
                "reason": "no bundle given; pass --bundle to see the item's text, "
                          "its passages and the diff against `expected`"}
    recorded = str((report.get("provenance") or {}).get("dataset_sha256", ""))
    if recorded and bundle.dataset_sha256 != recorded:
        # Not an ExplainError: this is the evidence not matching the record, which is the
        # same class of problem as a bundle failing its own seal, and it gets the same
        # refusal. An unknown item id is a question this report cannot answer (exit 2); a
        # mismatched bundle is a question it must not be allowed to answer wrongly (exit 3).
        raise IntegrityError(
            f"this bundle is not the one the report was produced from: the report names "
            f"dataset {recorded[:12]} and this bundle is {bundle.dataset_sha256[:12]}"
        )
    item = next((i for i in bundle.items if i.id == item_id), None)
    if item is None:
        return {"available": False,
                "reason": f"the bundle holds no item {item_id}, though the report scored one"}
    response = bundle.response_for(item.id)
    return {
        "available": True,
        "lang": item.lang,
        "behavior": item.behavior,
        "load_bearing": item.load_bearing,
        "fact_id": item.fact_id,
        "group": item.group,
        "prompt": item.prompt,
        "responded": response is not None,
        "response": response,
        "diff": _diff_against_expected(item, response or ""),
        "passages": _passages(bundle, item),
        "forbidden": list(item.forbidden),
        "forbidden_claims": list(item.forbidden_claims),
    }


def explain(report: dict[str, Any], item_id: str, bundle: Bundle | None = None
            ) -> dict[str, Any]:
    """Everything this run recorded about one item.

    Raises `ExplainError` if no suite in the report read the item. An id the report does not
    know is a question this report cannot answer, and answering it with an empty page would
    read as "nothing was wrong with it".
    """
    views = suite_views(report, item_id)
    if not views:
        known = sorted({
            value
            for suite in report.get("suites", [])
            for record in suite.get("items", [])
            for key in _ITEM_KEYS
            for value in ([record[key]] if isinstance(record.get(key), str)
                          else record.get(key) or [])
            if isinstance(value, str)
        })
        raise ExplainError(
            f"no suite in this report read an item called {item_id!r}; "
            f"the report holds {len(known)} item ids"
        )
    provenance = report.get("provenance") or {}
    return {
        "item": item_id,
        "report": {
            "run_id": provenance.get("run_id"),
            "dataset": (report.get("dataset") or {}).get("name"),
            "dataset_id": provenance.get("dataset_id"),
            "target": report.get("target"),
            "verdict": report.get("verdict"),
        },
        "suites": [
            {
                "suite": v.suite,
                "suite_score": v.suite_score,
                "floor": v.floor,
                "suite_verdict": v.suite_verdict,
                "n": v.n,
                "matched_on": v.matched_on,
                "metric": v.metric,
                "hard_failure": v.hard_failure,
                "contribution": v.contribution,
                "contribution_note": v.contribution_note,
                "records": list(v.records),
            }
            for v in views
        ],
        "couplings": list(coupling_lines(report, item_id)),
        "bundle": bundle_view(bundle, report, item_id),
    }


def _effect(view: dict[str, Any]) -> str:
    if view["hard_failure"]:
        return ("fails this suite on its own: a load-bearing check was wrong, and the pooled "
                "average does not get to absorb it")
    verdicts = {str(r.get("verdict")) for r in view["records"] if r.get("verdict")}
    if "UNVERIFIABLE" in verdicts:
        return "is not scored here: the suite reported it UNVERIFIABLE"
    return "is counted into the suite's pooled score"


def _expected_comparison_lines(bundle: dict[str, Any], *, lead: str = "") -> list[str]:
    """The against-`expected` diff, rendered inside the suite that is scored on it.

    A score of 0.6842 does not tell a reader that the answer says 900 where the reference says
    850. This does, and it sits under the suite whose number it explains rather than in a
    separate section the reader has to join up by hand.
    """
    if not bundle.get("available"):
        return [f"The answer and `expected` are not shown: {bundle['reason']}.", ""]
    diff = bundle["diff"]
    if not diff.get("available"):
        return [f"No comparison against `expected`: {diff['reason']}.", ""]
    return ([lead, ""] if lead else []) + [
        f"- Numbers the answer states that `expected` does not: "
        f"{diff['added_numbers'] or 'none'}.",
        f"- Numbers `expected` states that the answer does not: "
        f"{diff['missing_numbers'] or 'none'}.",
        f"- Tokens shared: {diff['shared_tokens']}; "
        f"missing from the answer: {diff['missing_tokens'] or 'none'}; "
        f"added by the answer: {diff['added_tokens'] or 'none'}.",
        "",
    ]


def render_markdown(explanation: dict[str, Any]) -> str:
    """The explanation as text. Deterministic: no clock, no set iteration order."""
    meta = explanation["report"]
    out: list[str] = [
        f"# {explanation['item']}",
        "",
        f"Run `{meta['run_id']}`, dataset `{meta['dataset']}` (`{meta['dataset_id']}`), "
        f"target `{meta['target']}`. This run's verdict: **{meta['verdict']}**.",
        "",
        f"Read by {len(explanation['suites'])} "
        f"{'suite' if len(explanation['suites']) == 1 else 'suites'}.",
        "",
    ]
    for view in explanation["suites"]:
        out += [
            f"## {view['suite']}",
            "",
            f"Suite scored {view['suite_score']:.4f} against a floor of {view['floor']:.4f}: "
            f"**{view['suite_verdict']}**, over {view['n']} items.",
            "",
            f"This item {_effect(view)}.",
            "",
        ]
        if view["contribution"] is None:
            out += [f"Share of the suite's score: not applicable, {view['contribution_note']}.",
                    ""]
        else:
            out += [f"Share of the suite's score: {view['contribution']:.4f} "
                    f"({view['contribution_note']}).", ""]
        if view["matched_on"] == "pair":
            out += ["Matched as one of a compared pair, so each record below names the other "
                    "item it was compared against.", ""]
        for record in view["records"]:
            out.append(f"- `{json.dumps(record, sort_keys=True, ensure_ascii=False)}`")
        out.append("")
        if view["metric"] == _EXPECTED_COMPARISON_METRIC:
            out += _expected_comparison_lines(
                explanation["bundle"],
                lead="This suite's score is that comparison, so here it is in words:")
    bundle = explanation["bundle"]
    out += ["## The item itself", ""]
    if not bundle.get("available"):
        out += [f"Not shown: {bundle['reason']}.", ""]
    else:
        out += [
            f"Asked in `{bundle['lang']}`, behavior `{bundle['behavior']}`"
            + (", load-bearing" if bundle["load_bearing"] else "")
            + (f", fact `{bundle['fact_id']}`" if bundle["fact_id"] else "")
            + ".",
            "",
            f"**Prompt.** {bundle['prompt']}",
            "",
        ]
        if not bundle["responded"]:
            out += ["**Answer.** No response was recorded for this item.", ""]
        else:
            out += [f"**Answer.** {bundle['response']}", ""]
        diff = bundle["diff"]
        out += ["### Against `expected`", ""]
        if not diff.get("available"):
            out += [f"Not shown: {diff['reason']}.", ""]
        else:
            out += [f"**Expected.** {diff['expected']}", ""]
            out += _expected_comparison_lines(bundle)
        out += ["### Passages", ""]
        if not bundle["passages"]:
            out += ["This item declares no passages.", ""]
        for passage in bundle["passages"]:
            role = "answering source" if passage["answering_source"] else "retrieved only"
            if passage.get("not_among_retrieved"):
                role = "answering source the target never retrieved"
            out.append(f"- `{passage['id']}` ({role})")
        out.append("")
        out += ["### Screened language", ""]
        out += [
            f"Declared `forbidden`: {bundle['forbidden'] or 'none'}.",
            f"Declared `forbidden_claims`: {bundle['forbidden_claims'] or 'none'}.",
            "",
            "Which of them were found is in the suite records above, as the screening suites "
            "recorded them. This command does not screen the response again.",
            "",
        ]
    out += ["## Couplings", ""]
    if not explanation["couplings"]:
        out += ["No coupling entry in this run names this item.", ""]
    for line in explanation["couplings"]:
        out.append(f"- {line}")
    if explanation["couplings"]:
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def render_json(explanation: dict[str, Any]) -> str:
    return json.dumps(explanation, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
