"""Per-target configuration (TOML), read with stdlib tomllib.

Selection of enabled suites and their floors is per-target configuration; the
harness ships demonstration defaults only. Malformed config, unknown suites,
or an empty suite selection are configuration errors (exit 4) — an audit with
zero suites would be a vacuous pass, and there is no vacuous pass.

Every key inside a `[suites.<id>]` table has to be one this file knows. A
typo in a key name is silently ignored by TOML, and a silently ignored
`floor` leaves the suite running at the harness's *demonstration* default —
a gate quietly weaker than the reviewable file that configures it appears to
say. The same reasoning governs `enabled`, which has to be a real boolean:
`enabled = 0` reads as "off" to a person and switches the suite off with no
word said, and `enabled = "false"` is a non-empty string, so it reads as
"off" to a person and leaves the suite on.

What this file records but does not refuse is the *shape* of a selection: a
configuration that enables two suites out of fifteen is legitimate, and
`TargetConfig.unscored` carries the other thirteen through to the report so
the run discloses them. See `scope.py` and
`docs/adr/0004-unscored-suites-are-disclosed-not-enforced.md`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import suites as suite_registry
from .scope import ABSENT, DISABLED


class ConfigError(Exception):
    """Malformed or unusable target configuration (exit 4)."""


# Everything a `[suites.<id>]` table may say. Anything else is a typo, and a
# typo here is not cosmetic: TOML ignores the unknown key, the suite falls
# back to a demonstration default, and the gate then runs at a bar the
# configuration file does not state anywhere.
SUITE_KEYS = frozenset({"enabled", "floor"})


@dataclass
class TargetConfig:
    name: str
    dataset_path: Path
    judge: dict[str, Any] = field(default_factory=lambda: {"kind": "lexical"})
    # suite id -> floor, enabled suites only
    suites: dict[str, float] = field(default_factory=dict)
    # Implemented suites this configuration does not score, suite id -> the
    # reason (`scope.ABSENT` or `scope.DISABLED`). Carried so the report can
    # disclose what the run left out rather than only what it covered.
    unscored: dict[str, str] = field(default_factory=dict)
    # Committed baseline record to compare this run against, if any.
    baseline_path: Path | None = None
    # How `plumbline record` reaches the live target. Read by that command and
    # by nothing else: an audit grades the committed bundle, so declaring an
    # adapter here can never put a network call inside the gate.
    adapter: dict[str, Any] = field(default_factory=dict[str, Any])
    # Question set to record against, when it is not the dataset being graded.
    questions_path: Path | None = None


def load_config(path: Path) -> TargetConfig:
    path = Path(path)
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e

    target = raw.get("target", {})
    name = target.get("name")
    if not name or not isinstance(name, str):
        raise ConfigError(f"{path}: [target].name (string) is required")

    dataset = raw.get("dataset", {})
    ds_path = dataset.get("path")
    if not ds_path or not isinstance(ds_path, str):
        raise ConfigError(f"{path}: [dataset].path (string) is required")
    # Relative paths resolve against the config file's directory, so the same
    # config works from any working directory (clean-checkout rule).
    dataset_path = _resolve(path, ds_path)

    baseline = raw.get("baseline", {})
    if not isinstance(baseline, dict):
        raise ConfigError(f"{path}: [baseline] must be a table")
    baseline_raw = baseline.get("path")
    if baseline_raw is not None and not isinstance(baseline_raw, str):
        raise ConfigError(f"{path}: [baseline].path must be a string")
    baseline_path = _resolve(path, baseline_raw) if baseline_raw else None

    judge = dict(raw.get("judge", {"kind": "lexical"}))
    if not isinstance(raw.get("judge", {}), dict):
        raise ConfigError(f"{path}: [judge] must be a table")
    # A judgment cache is a path like any other: resolved against the config
    # file's directory so the same config works from any working directory.
    # The resolved path never reaches the judge configuration hash — reports
    # carry no filesystem paths; the cache's *contents* are what is hashed.
    if "cache" in judge:
        if not isinstance(judge["cache"], str):
            raise ConfigError(f"{path}: [judge].cache must be a string path")
        judge["cache"] = str(_resolve(path, judge["cache"]))

    adapter = raw.get("adapter", {})
    if not isinstance(adapter, dict):
        raise ConfigError(f"{path}: [adapter] must be a table")
    questions_raw = adapter.get("questions")
    if questions_raw is not None and not isinstance(questions_raw, str):
        raise ConfigError(f"{path}: [adapter].questions must be a string path")
    questions_path = _resolve(path, questions_raw) if questions_raw else None
    # A subprocess adapter's working directory is a path like any other:
    # resolved against the config file, so the same config records the same
    # program from any working directory.
    if "workdir" in adapter:
        if not isinstance(adapter["workdir"], str):
            raise ConfigError(f"{path}: [adapter].workdir must be a string path")
        adapter = dict(adapter)
        adapter["workdir"] = str(_resolve(path, adapter["workdir"]))

    available = suite_registry.available()
    declared = raw.get("suites", {})
    if not isinstance(declared, dict):
        raise ConfigError(f"{path}: [suites] must be a table")
    enabled: dict[str, float] = {}
    for suite_id, spec in declared.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"{path}: [suites.{suite_id}] must be a table")
        if suite_id not in available:
            raise ConfigError(
                f"{path}: unknown suite '{suite_id}' "
                f"(available: {', '.join(sorted(available))})"
            )
        unknown = sorted(set(spec) - SUITE_KEYS)
        if unknown:
            raise ConfigError(
                f"{path}: [suites.{suite_id}] sets unknown key(s) "
                f"{', '.join(repr(k) for k in unknown)}; known keys are "
                f"{', '.join(sorted(SUITE_KEYS))}. A misspelled key is not a "
                f"harmless one: TOML ignores it, the suite falls back to the "
                f"harness's demonstration default, and the gate then runs at "
                f"a bar this file does not state."
            )
        switch = spec.get("enabled", True)
        if not isinstance(switch, bool):
            raise ConfigError(
                f"{path}: [suites.{suite_id}].enabled must be true or false, "
                f"not {switch!r}. `0` and `\"false\"` are not booleans in "
                f"TOML: one switches the suite off without saying so and the "
                f"other leaves it on."
            )
        if not switch:
            continue
        cls = available[suite_id]
        if not cls.implemented:
            raise ConfigError(
                f"{path}: suite '{suite_id}' is a skeleton planned for "
                f"{cls.planned_milestone}; enabling it is an error, not a skip"
            )
        floor = spec.get("floor", cls.default_floor)
        if (not isinstance(floor, (int, float)) or isinstance(floor, bool)
                or not (0.0 <= float(floor) <= 1.0)):
            raise ConfigError(f"{path}: [suites.{suite_id}].floor must be in [0, 1]")
        if float(floor) == 0.0:
            # Every score in [0,1] clears a floor of zero, including a 0.0
            # from a suite that measured nothing. A suite configured that way
            # is a green row that cannot go red: it costs a run and reports a
            # verdict, and the verdict is unconditional. That is the vacuous
            # pass this file already refuses at the whole-audit level, one
            # suite at a time.
            raise ConfigError(
                f"{path}: [suites.{suite_id}].floor is 0, which every possible "
                f"score clears. A suite that cannot fail is not a check; set a "
                f"floor the target has to reach, or set "
                f"[suites.{suite_id}].enabled = false and say in review why "
                f"this target is not held to it."
            )
        enabled[suite_id] = float(floor)

    if not enabled:
        raise ConfigError(
            f"{path}: no suites enabled; an audit with zero suites would be a "
            f"vacuous pass, and there is no vacuous pass"
        )

    # What this configuration does NOT hold the target to. A skeleton suite is
    # not in here: it is not something a configuration could have run, and
    # enabling one is already an error above.
    unscored = {
        suite_id: (DISABLED if suite_id in declared else ABSENT)
        for suite_id, cls in sorted(available.items())
        if cls.implemented and suite_id not in enabled
    }

    return TargetConfig(name=name, dataset_path=dataset_path, judge=judge,
                        suites=enabled, unscored=unscored,
                        baseline_path=baseline_path,
                        adapter=adapter, questions_path=questions_path)


def _resolve(config_path: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (config_path.parent / candidate).resolve()
