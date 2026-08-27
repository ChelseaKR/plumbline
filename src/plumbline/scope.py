"""What this run's configuration left outside the gate.

Every report has always listed the suites that ran. None of them listed the
suites that did not, and the two are not the same disclosure: a reader would
have to know the registry by heart to notice that `privacy` is missing from
a fourteen-row table of green results. `docs/responsible-tech.md` names that
gap as a misuse this repository can describe but not prevent:

    Enabling `smoke` and `accuracy` while leaving `adversarial` and `privacy`
    off is a valid configuration and a legitimate way to phase in coverage --
    and an easy way to produce a clean-looking report about a system nobody
    checked for the things those two suites exist to check.

Preventing it is not this module's business and would be the wrong thing to
build. Which suites a target is held to is a policy decision made by the
people accountable for that target, in a reviewable file, and the same
document is explicit that "nothing in this harness second-guesses a floor a
human committed to a reviewable file." Refusing a partial configuration
would refuse the legitimate case -- phasing coverage in -- along with the
evasive one, and the harness cannot tell them apart.

What it does instead is take the work of noticing off the reader. Every
report now carries the other half of the suite table: the implemented suites
this configuration did not score, and which of the two reasons applies.

    absent    the configuration never mentions the suite at all
    disabled  the configuration names it and sets `enabled = false`

Both are stated because they read very differently in a review. `absent` is
usually a configuration written before the suite existed; `disabled` is a
decision somebody made and can be asked about.

The block never touches the verdict, the same way `couplings.py` never
touches it: this is disclosure, not enforcement. See
`docs/adr/0004-unscored-suites-are-disclosed-not-enforced.md` for the
alternatives that were weighed and refused, including failing the gate on a
partial configuration.

It is not optional and has no "clean" short circuit. The section renders
even when every suite ran, because a section that appears only on a partial
configuration teaches a reader to read its absence as a full one -- and the
absence of a warning is exactly the kind of evidence this harness refuses to
accept anywhere else. It is inside the report body, so the report seal
covers it: a scope claim cannot be edited off a report without breaking
`plumbline verify`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Why an implemented suite was not scored. Two reasons, and no third: a suite
# is either named in the configuration or it is not, and if it is named it is
# either switched on or off. `config.load_config` refuses everything else --
# an unknown suite id, a skeleton, a floor outside [0,1], a floor of zero, an
# `enabled` that is not a boolean -- before a run gets this far.
ABSENT = "absent"
DISABLED = "disabled"

_WHY = {
    ABSENT: "absent from the configuration",
    DISABLED: "`enabled = false` in the configuration",
}

NOTE = (
    "scope lists the implemented suites this configuration did not score. A "
    "verdict is only ever about the suites that ran; which suites a target "
    "is held to is a policy decision, and this block is here so reading the "
    "verdict does not require knowing the registry by heart"
)


def analyze(*, scored: Iterable[str],
            unscored: Mapping[str, str]) -> dict[str, Any]:
    """Build the scope block from a run's suite selection.

    `scored` is the suite ids this run evaluated; `unscored` maps every
    implemented suite it did not evaluate to one of the reasons above.
    Together they are the implemented registry, which is what makes the
    denominator below a real count rather than a restatement of the numerator.
    """
    scored_ids = sorted(scored)
    not_scored = [
        {"suite": suite_id, "reason": reason, "why": _WHY[reason]}
        for suite_id, reason in sorted(unscored.items())
    ]
    implemented = len(scored_ids) + len(not_scored)
    return {
        "implemented": implemented,
        "scored": len(scored_ids),
        "not_scored": not_scored,
        "summary": _summary(len(scored_ids), implemented, not_scored),
        "note": NOTE,
    }


def _grouped(not_scored: list[dict[str, Any]]) -> str:
    """`a and b (absent from the configuration), c (disabled in it)`."""
    parts = []
    for reason in (ABSENT, DISABLED):
        names = [entry["suite"] for entry in not_scored
                 if entry["reason"] == reason]
        if names:
            parts.append(f"{_join(names)} ({_WHY[reason].replace('`', '')})")
    return "; ".join(parts)


def _join(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _summary(scored: int, implemented: int,
             not_scored: list[dict[str, Any]]) -> str:
    if not not_scored:
        return (f"all {implemented} implemented suites were scored by this "
                f"run")
    return (
        f"{scored} of {implemented} implemented suites were scored. "
        f"{len(not_scored)} were not: {_grouped(not_scored)}. This run "
        f"reports nothing about what those suites check."
    )


def render_markdown(scope: dict[str, Any]) -> list[str]:
    """The `## Scope` section, rendered whether or not anything is missing."""
    lines = ["## Scope", ""]
    if not scope["not_scored"]:
        lines.append(
            f"All **{scope['implemented']}** implemented suites were scored "
            f"by this run.")
        lines.append("")
        return lines
    lines.append(
        f"**{scope['scored']} of {scope['implemented']}** implemented suites "
        f"were scored. **{len(scope['not_scored'])} were not**, so this run "
        f"reports nothing about what they check:")
    lines.append("")
    lines.append("| Suite | Why it was not scored |")
    lines.append("|---|---|")
    for entry in scope["not_scored"]:
        lines.append(f"| `{entry['suite']}` | {entry['why']} |")
    lines.append("")
    lines.append(
        "Which suites a target is held to is a policy decision, not a defect. "
        "This table is here so that reading the verdict does not also require "
        "knowing which suites exist.")
    lines.append("")
    return lines


def summarize_for_terminal(scope: dict[str, Any]) -> list[str]:
    """One line in the build log, which is the artifact people actually read.

    A verdict quoted out of its report loses the suite table with it. The
    build log is where a `PASS` is most often read and least often read
    alongside anything else, so the omission is named there too.
    """
    if not scope:
        return []
    if not scope["not_scored"]:
        return [f"scope: all {scope['implemented']} implemented suites scored"]
    listed = ", ".join(f"{e['suite']} ({e['reason']})"
                       for e in scope["not_scored"])
    return [
        f"scope: {scope['scored']} of {scope['implemented']} implemented "
        f"suites scored; NOT scored: {listed}",
    ]
