"""Suite framework: pluggable scorers with floors and pass/fail verdicts.

Every suite produces a score in [0,1], carries a declared floor, and renders a
PASS/FAIL verdict. The overall verdict fails if ANY enabled suite fails.
Enabling a suite that exists only as a skeleton is a configuration error —
the no-silent-skip rule applies to the registry itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..bundle import Bundle
from ..judges import Judge, normalize, strip_citations
from ..stats import KIND_PROPORTION

PASS = "PASS"
FAIL = "FAIL"

# A shared input, tagged on the per-item record of any suite that failed an
# item because of it. `couplings.py` reads these tags to say, from the run's
# own evidence rather than from an assertion, when several failing suites are
# one finding. Three suites screen every response against `item.forbidden`.
CAUSE_FORBIDDEN = "forbidden"

# Not a third verdict. A suite's verdict stays PASS or FAIL, because a third
# state at that level would be a silent skip wearing a label. UNVERIFIABLE is
# a per-ITEM outcome: the evidence does not let this item be checked, so it is
# excluded from the score, named in the report, and never counted as a pass.
UNVERIFIABLE = "UNVERIFIABLE"

# Reason ids for the standard `unverifiable` block. Two, because "the target
# returned nothing" and "the target returned characters with nothing in them"
# are different things to have to explain to a reader, and only the first one
# looks like a broken connection.
SILENT = "silent"
UNREADABLE = "unreadable"

SILENCE_NOTE = (
    "the target returned nothing a check could read for these items — an "
    "absent or empty response (`silent`), or one whose every character "
    "disappears under normalization: punctuation, emoji, zero-width "
    "characters, bare citation markers (`unreadable`). Silence satisfies every "
    "check phrased as an absence — it contains no forbidden phrase, discloses "
    "no personal data, states no number its sources lack, and cannot "
    "contradict the same question asked in another language. Counting that as "
    "evidence would let a target that answered nothing at all score a perfect "
    "1.00 here. These items are excluded from the score and named instead; "
    "`smoke` is the suite that fails on them, and the suites that ask whether "
    "the target behaved correctly score them zero."
)

_UNREADABLE_NOTE = {
    SILENT: ("the target returned nothing for this item, so this suite had "
             "nothing to check; excluded from the score, and not a pass"),
    UNREADABLE: ("the target's response for this item has no readable content "
                 "— every character in it disappears under normalization — so "
                 "this suite had nothing to check; excluded from the score, "
                 "and not a pass"),
}


def readable(text: str | None) -> bool:
    """Whether a recorded response contains anything a check can read.

    `bool(text.strip())` was the old test, and it is the wrong one: `"."`,
    `"🙂"` and a zero-width space are all non-empty strings that survive
    `strip()` and contain nothing. Under the judge's normalizer they are
    indistinguishable from silence — no content token, no number, no phrase to
    screen — so every suite that scores an absence handed them a perfect 1.00,
    which is the same vacuous pass an empty string used to buy.

    Citation markers are stripped first: a response consisting only of
    `[src-rent-cap]` asserts nothing either, and a source id is bookkeeping
    rather than an answer.
    """
    return bool(normalize(strip_citations(text or "")))


def unreadable_reason(bundle, item) -> str | None:
    """`SILENT`, `UNREADABLE`, or None when the response can be checked."""
    text = bundle.response_for(item.id) or ""
    if readable(text):
        return None
    return SILENT if not text.strip() else UNREADABLE


def responded(bundle, item) -> bool:
    """Whether the target said something this suite can actually read.

    The distinction this draws is the difference between "we checked and found
    nothing wrong" and "there was nothing to check". Every suite that screens a
    recorded response for the absence of something has to make it, or a dead
    target — or one emitting a single full stop — scores full marks.
    """
    return unreadable_reason(bundle, item) is None


def silence_record(item_id: str, reason: str = SILENT) -> dict:
    """The per-item record for an item excluded because nothing was said, or
    because what was said has nothing in it."""
    return {
        "item": item_id,
        "verdict": UNVERIFIABLE,
        "reason": reason,
        "note": _UNREADABLE_NOTE[reason],
    }


def split_unreadable(bundle, items) -> tuple[list, dict[str, list[str]]]:
    """(items whose response can be checked, reason id -> excluded item ids).

    Every suite that excludes unreadable responses does it the same way, so
    the split lives here: a suite that wrote its own would be one refactor away
    from checking `.strip()` again.
    """
    scorable, excluded = [], {SILENT: [], UNREADABLE: []}
    for item in items:
        reason = unreadable_reason(bundle, item)
        if reason is None:
            scorable.append(item)
        else:
            excluded[reason].append(item.id)
    return scorable, excluded


def unreadable_records(excluded: dict[str, list[str]]) -> list[dict]:
    """One per-item record per excluded item, in a deterministic order."""
    return [silence_record(item_id, reason)
            for reason, ids in sorted(excluded.items())
            for item_id in ids]


class EmptyPopulationError(Exception):
    """An enabled suite has nothing to score.

    Fail closed: a suite with no population is not a pass and not a skip. It
    means the target's configuration claims a property the evidence bundle
    cannot test, and the run says so and stops (configuration error).
    """


@dataclass
class SuiteResult:
    suite_id: str
    score: float          # in [0, 1]
    floor: float
    verdict: str          # PASS | FAIL
    n: int                # items considered
    details: dict = field(default_factory=dict)
    item_records: list[dict] = field(default_factory=list)

    # Severity: item ids that failed a load-bearing check and therefore fail
    # the suite regardless of the pooled average (spec R3).
    hard_failures: list[str] = field(default_factory=list)

    # What kind of statistic the score is, and the underlying units, so the
    # statistics module can attach an honest interval instead of guessing.
    # `sample` holds the per-unit scores that produced `score`; `strata` holds
    # them grouped, for suites whose score is a between-group comparison.
    score_kind: str = KIND_PROPORTION
    sample: list[float] = field(default_factory=list)
    strata: dict[str, list[float]] = field(default_factory=dict)

    # Filled in centrally by the audit runner; no suite can forget them.
    ci: dict | None = None
    mde: float | None = None
    stats_meta: dict = field(default_factory=dict)


class Suite:
    """Base class. Subclasses set `id`, `default_floor`, and implement
    `evaluate`. A subclass with implemented=False is a documented skeleton;
    the registry refuses to enable it."""

    id: str = ""
    default_floor: float = 1.0
    implemented: bool = True
    planned_milestone: str | None = None

    def evaluate(self, bundle: Bundle, judge: Judge, floor: float) -> SuiteResult:
        raise NotImplementedError

    @staticmethod
    def verdict_for(score: float, floor: float) -> str:
        return PASS if score >= floor else FAIL

    def require_population(self, units, requirement: str):
        """Refuse to score nothing. Returns `units` when non-empty."""
        if not units:
            raise EmptyPopulationError(
                f"suite '{self.id}' is enabled but this evidence bundle has "
                f"nothing for it to score: {requirement}. A suite with no "
                f"population is a configuration error, not a pass."
            )
        return units


def unverifiable_block(reasons: dict[str, list[str]], *, eligible: int,
                       scored: int, note: str) -> dict:
    """The standard shape for "what this suite could not check, and why".

    A suite that silently narrows its own population reports a score over
    whatever was left and reads exactly like a suite that checked everything.
    Any suite whose evidence can be missing puts this block in its `details`
    under the key `unverifiable`; both report formats then print the coverage
    line without knowing anything about the suite.

    `eligible` is how many items the suite would have liked to score,
    `scored` how many it could, and `reasons` maps a short reason id to the
    item ids it applies to.
    """
    counted = {reason: sorted(ids) for reason, ids in sorted(reasons.items())
               if ids}
    return {
        "count": sum(len(ids) for ids in counted.values()),
        "eligible": eligible,
        "scored": scored,
        "reasons": counted,
        "note": note,
    }


_REGISTRY: dict[str, type[Suite]] = {}


def register(cls: type[Suite]) -> type[Suite]:
    if not cls.id:
        raise ValueError(f"suite class {cls.__name__} has no id")
    if cls.id in _REGISTRY:
        raise ValueError(f"duplicate suite id '{cls.id}'")
    _REGISTRY[cls.id] = cls
    return cls


def available() -> dict[str, type[Suite]]:
    _load_all()
    return dict(_REGISTRY)


def get(suite_id: str) -> Suite:
    """Instantiate a suite for evaluation. Unknown or unimplemented suites
    raise — fail closed, never skip."""
    _load_all()
    cls = _REGISTRY.get(suite_id)
    if cls is None:
        raise KeyError(
            f"unknown suite '{suite_id}' (available: {', '.join(sorted(_REGISTRY))})"
        )
    if not cls.implemented:
        raise KeyError(
            f"suite '{suite_id}' is a skeleton planned for "
            f"{cls.planned_milestone or 'a later milestone'}; enabling it is an "
            f"error, not a skip"
        )
    return cls()


def _load_all() -> None:
    # Import side effects populate the registry exactly once.
    from . import (  # noqa: F401
        accessibility,
        accuracy,
        adversarial,
        attribution,
        conduct,
        conversational_integrity,
        cross_language,
        fairness,
        grounding,
        multilingual,
        refusal,
        skeletons,
        smoke,
    )
