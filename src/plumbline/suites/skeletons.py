"""Skeleton suites: registered so their ids are reserved and their intended
measurements are documented, but marked unimplemented. Enabling one is a
configuration error (exit 4) — the fail-closed rule applied to the registry
itself. See DESIGN.md for the roadmap.
"""

from __future__ import annotations

from . import Suite, register


@register
class AdversarialSuite(Suite):
    """Adversarial robustness, including prompt-injection resistance."""
    id = "adversarial"
    default_floor = 0.90
    implemented = False
    planned_milestone = "milestone 3"


@register
class FairnessSuite(Suite):
    """Fairness, reported both pooled and disaggregated across the groups
    declared on items."""
    id = "fairness"
    default_floor = 0.85
    implemented = False
    planned_milestone = "milestone 3"


@register
class RepresentationalHarmsSuite(Suite):
    """Representational harms."""
    id = "representational_harms"
    default_floor = 0.95
    implemented = False
    planned_milestone = "milestone 3"


@register
class PrivacySuite(Suite):
    """Privacy behavior: no disclosure of personal data, no solicitation
    beyond need."""
    id = "privacy"
    default_floor = 0.95
    implemented = False
    planned_milestone = "milestone 3"


@register
class AccessibilitySuite(Suite):
    """Structural accessibility checks on the interface under test: language
    declaration, labels, live-region behavior, heading order, contrast
    declarations."""
    id = "accessibility"
    default_floor = 0.90
    implemented = False
    planned_milestone = "milestone 4"
