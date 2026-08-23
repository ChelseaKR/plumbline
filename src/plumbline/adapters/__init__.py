"""Live-target adapters: the part that talks to the system under test.

Plumbline grades an evidence bundle. Until now something else had to produce
the `responses.jsonl` inside it. An adapter is that something: it takes a
*question set* (a sealed bundle of items with no responses yet), asks a live
target each item's prompt, and writes a new, sealed evidence bundle.

Three rules hold the design together, and all three are enforced, not
promised:

1. **Recording is a separate command.** `plumbline record` uses adapters;
   `plumbline audit` and `plumbline gate` never import this package. The gate
   stays offline and deterministic, and no target configuration can make it
   otherwise. `tests/test_adapters.py` asserts the import never happens.
2. **Recording writes a new bundle, never over the old one.** The question set
   it was recorded against is named, by hash, in the new bundle's manifest.
   Evidence is append-only in the way that matters: you can always see what
   was asked and what answered.
3. **A failed call is not a low score.** By default the recorder aborts, so a
   half-recorded transcript can never be graded as if the target had merely
   done badly.

Two kinds ship. `http_json` talks to a service; `subprocess` runs a local
program, which fits the offline-first default better than HTTP does — a
subprocess recording opens no socket at all. Both are bounded the same way:
explicit timeouts, explicit size ceilings, secrets from the environment by
name, and unknown configuration keys refused rather than ignored.

Adding an adapter kind means adding a module here and registering it. The
registry refuses an unknown kind rather than falling back to anything.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from ..bundle import Item
from ..errors import OutboundError


class AdapterError(OutboundError):
    """The adapter is misconfigured or the target did not answer usably
    (configuration / environment error, exit 4)."""


class Adapter(Protocol):
    kind: str

    def describe(self) -> dict[str, Any]:
        """Non-secret provenance recorded in the bundle manifest."""

    def respond(self, item: Item) -> str:
        """The target's answer to one item, or raise AdapterError."""


def _factories() -> dict[str, Any]:
    from . import http_json, subprocess_cli
    return {
        http_json.HttpJsonAdapter.kind: http_json.HttpJsonAdapter,
        subprocess_cli.SubprocessAdapter.kind: subprocess_cli.SubprocessAdapter,
    }


def available() -> tuple[str, ...]:
    return tuple(sorted(_factories()))


def make_adapter(config: dict[str, Any]) -> tuple[Adapter, list[str]]:
    """Build the adapter a target configuration declares.

    Returns the adapter and any warnings worth printing (never fatal). An
    unknown or missing kind is an error: there is no default adapter, because
    guessing how to talk to somebody's chat system is not a thing a harness
    should do quietly.
    """
    if not isinstance(config, dict) or not config:
        raise AdapterError(
            "no [adapter] table in the target configuration; `plumbline "
            "record` needs one to know what to talk to"
        )
    kind = config.get("kind")
    factories = _factories()
    if kind not in factories:
        raise AdapterError(
            f"unknown adapter kind {kind!r} (implemented: "
            f"{', '.join(available())})"
        )
    return cast("tuple[Adapter, list[str]]", factories[kind].from_config(config))
