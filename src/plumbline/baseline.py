"""Baseline regression comparison (milestone 3 skeleton).

Planned behavior:

- A stored baseline is a prior committed report.json.
- Comparison names every suite whose verdict changed since the baseline.
- If the baseline's dataset hash differs from the current run's, the harness
  REFUSES numeric comparison and says so explicitly in the report — comparing
  incomparable runs is worse than not comparing. Verdict-flip naming still
  notes the incomparability.
"""

from __future__ import annotations


def compare(current_report: dict, baseline_report: dict) -> dict:
    raise NotImplementedError("planned for milestone 3; see DESIGN.md roadmap")
