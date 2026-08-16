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
"""

from __future__ import annotations

from ..bundle import Bundle
from ..judges import Judge
from ..stats import KIND_PROPORTION
from . import Suite, SuiteResult, register


@register
class MultilingualSuite(Suite):
    id = "multilingual"
    # One wrong-language answer in a twenty-item bundle is already a service
    # failure for a whole language community, but a floor of exactly 1.00
    # belongs to structural checks; 0.95 is the demonstration default.
    default_floor = 0.95

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        supported = set(judge.supported_languages())
        unsupported = sorted({i.lang for i in bundle.items} - supported)
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
        mismatches, undetermined = [], []
        for item in bundle.items:
            response = bundle.response_for(item.id) or ""
            detected = judge.detect_language(response)
            ok = detected == item.lang
            sample.append(1.0 if ok else 0.0)
            record = {
                "item": item.id,
                "score": 1.0 if ok else 0.0,
                "asked_in": item.lang,
                "answered_in": detected or "undetermined",
            }
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
                    f"asked in {item.lang}, answered in {detected}"
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
