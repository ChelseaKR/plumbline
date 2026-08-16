"""Per-target configuration (TOML), read with stdlib tomllib.

Selection of enabled suites and their floors is per-target configuration; the
harness ships demonstration defaults only. Malformed config, unknown suites,
or an empty suite selection are configuration errors (exit 4) — an audit with
zero suites would be a vacuous pass, and there is no vacuous pass.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import suites as suite_registry


class ConfigError(Exception):
    """Malformed or unusable target configuration (exit 4)."""


@dataclass
class TargetConfig:
    name: str
    dataset_path: Path
    judge: dict = field(default_factory=lambda: {"kind": "lexical"})
    # suite id -> floor, enabled suites only
    suites: dict[str, float] = field(default_factory=dict)
    # Committed baseline record to compare this run against, if any.
    baseline_path: Path | None = None
    # How `plumbline record` reaches the live target. Read by that command and
    # by nothing else: an audit grades the committed bundle, so declaring an
    # adapter here can never put a network call inside the gate.
    adapter: dict = field(default_factory=dict)
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
    enabled: dict[str, float] = {}
    for suite_id, spec in raw.get("suites", {}).items():
        if not isinstance(spec, dict):
            raise ConfigError(f"{path}: [suites.{suite_id}] must be a table")
        if suite_id not in available:
            raise ConfigError(
                f"{path}: unknown suite '{suite_id}' "
                f"(available: {', '.join(sorted(available))})"
            )
        if not spec.get("enabled", True):
            continue
        cls = available[suite_id]
        if not cls.implemented:
            raise ConfigError(
                f"{path}: suite '{suite_id}' is a skeleton planned for "
                f"{cls.planned_milestone}; enabling it is an error, not a skip"
            )
        floor = spec.get("floor", cls.default_floor)
        if not isinstance(floor, (int, float)) or not (0.0 <= float(floor) <= 1.0):
            raise ConfigError(f"{path}: [suites.{suite_id}].floor must be in [0, 1]")
        enabled[suite_id] = float(floor)

    if not enabled:
        raise ConfigError(
            f"{path}: no suites enabled; an audit with zero suites would be a "
            f"vacuous pass, and there is no vacuous pass"
        )

    return TargetConfig(name=name, dataset_path=dataset_path, judge=judge,
                        suites=enabled, baseline_path=baseline_path,
                        adapter=adapter, questions_path=questions_path)


def _resolve(config_path: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (config_path.parent / candidate).resolve()
