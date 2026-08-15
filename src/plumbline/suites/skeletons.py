"""Skeleton suites: registered so their ids are reserved and their intended
measurements are documented, but marked unimplemented. Enabling one is a
configuration error (exit 4) — the fail-closed rule applied to the registry
itself. See DESIGN.md for the roadmap.

The list is empty: every suite in the specification's taxonomy is implemented.
The module and the registry's refusal to enable an unimplemented suite stay,
because the next suite anyone adds should start here.
"""

from __future__ import annotations
