"""Skeleton suites: registered so their ids are reserved and their intended
measurements are documented, but marked unimplemented. Enabling one is a
configuration error (exit 4) — the fail-closed rule applied to the registry
itself. See DESIGN.md for the roadmap.
"""

from __future__ import annotations

from . import Suite, register


@register
class AccessibilitySuite(Suite):
    """Structural accessibility checks on the interface under test: language
    declaration, labels, live-region behavior, heading order, contrast
    declarations."""
    id = "accessibility"
    default_floor = 1.00
    implemented = False
    planned_milestone = "milestone 4"
