"""Multilingual fidelity: did the system answer in the language it was asked
in?

Cross-language *agreement* (the `cross_language` suite) asks whether two
languages tell the same story. This suite asks the prior question: whether a
speaker who wrote in Spanish got Spanish back. A system that silently answers
in English is unusable for the person who asked, however accurate the content,
and pooled accuracy will not show it — the English answer may well score well
against an English reference.

Language identification is a deterministic function-word profile, shipped in
`lexicons.py` and covered by the judge configuration hash. It is coarse by
design: it separates the languages the bundle actually uses, and it refuses to
guess. A response it cannot place counts as a failure, never as a pass — the
harness does not award credit for evidence it could not read.

An item written in a language with no shipped profile is a configuration
error. Scoring it would mean scoring nothing and calling it a pass.

An item may declare `expected_response_lang`, and then that is what this suite
scores against instead of the language the question was written in. The case it
exists for was reported by a consumer: an English-only corpus, an Arabic
question, and a product that answers by quoting the English passage under an
Arabic notice saying it did so. That is the correct behaviour for that corpus
and this suite scored it 0.0000 — the same number a system that simply ignored
the question's language gets. Two opposite behaviours are not one score.

The declaration is not an inference and is never made here. Only the bundle can
say that an English answer to an Arabic question was intended, it must say why,
and the report publishes how many items rest on one, so a reader can see how
much of the score is a declaration rather than a measurement. A declared
language with no shipped profile is the same configuration error as an item's
own would be.
"""

from __future__ import annotations

from ..bundle import Bundle, Item
from ..judges import Judge
from ..stats import KIND_PROPORTION
from . import Suite, SuiteResult, register


def _declaration_details(declaring: list[str]) -> dict[str, object]:
    """The declaration block, present only when something declared.

    A bundle that declares nothing has to produce the report it produced before
    this field existed, down to the byte, so the keys are added rather than
    emitted empty. Two empty lists and two paragraphs about them would be the
    whole diff of a change that did nothing.
    """
    if not declaring:
        return {}
    return {
        "items_declaring_expected_response_lang": declaring,
        "declaration_note": (
            "these items were scored against a language the bundle declares, "
            "not the one the question was written in. The declaration is the "
            "dataset's, never this harness's, and each one carries its stated "
            "reason in the item record"
        ),
    }


def _expected_lang(item: Item) -> str:
    """The language this item's answer is supposed to be in.

    One function, read by the profile check and by the scoring loop, so the two
    cannot come apart: a declared language the profile check never saw would
    make every one of that item's runs a silent zero.
    """
    if item.expected_response_lang is not None:
        return str(item.expected_response_lang["lang"])
    return item.lang


@register
class MultilingualSuite(Suite):
    id = "multilingual"
    # One wrong-language answer in a twenty-item bundle is already a service
    # failure for a whole language community, but a floor of exactly 1.00
    # belongs to structural checks; 0.95 is the demonstration default.
    default_floor = 0.95

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        supported = set(judge.supported_languages())
        # Declared languages join the check. A declaration naming a language no
        # profile covers would otherwise send every one of its items down the
        # `detected is None` branch and score them zero for a reason that is a
        # configuration error, not a target failure.
        asked = {i.lang for i in bundle.items}
        declared = {_expected_lang(i) for i in bundle.items}
        unsupported = sorted((asked | declared) - supported)
        if unsupported:
            raise ValueError(
                f"suite '{self.id}' cannot judge items written in "
                f"{', '.join(unsupported)}: no language profile is in force "
                f"for them (available: {', '.join(sorted(supported))}). "
                f"Scoring them would mean scoring nothing and calling it a "
                f"pass. Declare the language in your target configuration — "
                f"[judge.languages." + unsupported[0] + "] with `script` "
                f"(a distinctive script, e.g. script = [\"0600-06FF\"]) or "
                f"`words` (a list of function words) — rather than disabling "
                f"the suite for the language communities it exists to serve."
            )

        records, sample = [], []
        mismatches, undetermined, cross_language = [], [], []
        for item in bundle.items:
            response = bundle.response_for(item.id) or ""
            detected = judge.detect_language(response)
            expected = _expected_lang(item)
            ok = detected == expected
            sample.append(1.0 if ok else 0.0)
            record = {
                "item": item.id,
                "score": 1.0 if ok else 0.0,
                "asked_in": item.lang,
                "answered_in": detected or "undetermined",
            }
            # Written only when a declaration moved the target. For every other
            # item `expected_in` would restate `asked_in`, and an item record
            # that grows a key saying nothing new is a published artifact that
            # changed for no reason a reader can act on.
            if item.expected_response_lang is not None:
                cross_language.append(item.id)
                record["expected_in"] = expected
                record["declaration"] = "expected_response_lang"
                record["declared_reason"] = item.expected_response_lang["reason"]
            if detected is None:
                undetermined.append(item.id)
                record["note"] = (
                    "no shipped language profile matched this response; "
                    "counted as a failure, because unreadable evidence is not "
                    "evidence of success"
                )
            elif not ok:
                mismatches.append(item.id)
                record["note"] = (
                    f"asked in {item.lang}, expected {expected}, answered in "
                    f"{detected}"
                )
            records.append(record)

        n = len(sample)
        score = sum(sample) / n if n else 0.0
        unreviewed = [
            i.id for i in bundle.items
            if i.translation and i.translation.get("review") == "unreviewed"
        ]
        return SuiteResult(
            suite_id=self.id,
            score=score,
            floor=floor,
            verdict=self.verdict_for(score, floor),
            n=n,
            details={
                "metric": "fraction of responses in the language the item was "
                          "asked in",
                "language_mismatches": mismatches,
                "undetermined_language": undetermined,
                "languages_in_bundle": sorted({i.lang for i in bundle.items}),
                **_declaration_details(cross_language),
                "unreviewed_translations": unreviewed,
                "unreviewed_note": (
                    "unreviewed translations are reported here and warned about "
                    "on every run; they never affect this score or the verdict"
                ),
            },
            item_records=records,
            score_kind=KIND_PROPORTION,
            sample=sample,
        )
