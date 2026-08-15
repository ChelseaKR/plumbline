"""Suite framework: pluggable scorers with floors and pass/fail verdicts.

Every suite produces a score in [0,1], carries a declared floor, and renders a
PASS/FAIL verdict. The overall verdict fails if ANY enabled suite fails.
Enabling a suite that exists only as a skeleton is a configuration error —
the no-silent-skip rule applies to the registry itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..bundle import Bundle
from ..judges import Judge
from ..stats import KIND_PROPORTION

PASS = "PASS"
FAIL = "FAIL"


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
        accuracy,
        adversarial,
        conduct,
        cross_language,
        fairness,
        grounding,
        multilingual,
        refusal,
        skeletons,
        smoke,
    )
