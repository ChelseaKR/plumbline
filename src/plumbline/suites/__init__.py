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

PASS = "PASS"
FAIL = "FAIL"


@dataclass
class SuiteResult:
    suite_id: str
    score: float          # in [0, 1]
    floor: float
    verdict: str          # PASS | FAIL
    n: int                # items considered
    details: dict = field(default_factory=dict)
    item_records: list[dict] = field(default_factory=list)
    # Statistical honesty fields; populated in milestone 2 (Wilson CI, MDE).
    ci: dict | None = None
    mde: float | None = None


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
    from . import smoke, accuracy, refusal, skeletons  # noqa: F401
