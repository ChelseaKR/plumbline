"""Statistical honesty (milestone 2 skeleton).

Planned per-suite additions to every report:

- Wilson score confidence interval for proportion-style suite scores, so a
  reader sees the uncertainty band around the score at the sample size used.
- Minimum detectable effect (MDE) at the sample size used, so a reader can see
  how small a regression the run could even have caught.

Report schemas already carry `ci` and `mde` fields (null until this lands), so
implementing this module changes values, not formats.
"""

from __future__ import annotations


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    raise NotImplementedError("planned for milestone 2; see DESIGN.md roadmap")


def minimum_detectable_effect(n: int, confidence: float = 0.95, power: float = 0.80) -> float:
    raise NotImplementedError("planned for milestone 2; see DESIGN.md roadmap")
