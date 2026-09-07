"""`[adapter.conversation]`: how a multi-turn item is actually carried.

`bundle.py`'s `Item.turns` and `turn_responses` (ADR 0003) let an evidence
bundle hold a whole conversation, and `conversational_integrity` grades every
turn of one. Until now `plumbline record` did not know the fields existed: it
asked one prompt per item, so the only multi-turn evidence that could be
graded was evidence somebody produced by other means.

The missing piece was never the loop. It is that **there is no universal way
to send a second turn.** One service wants the whole history back in the
request body; another hands out a session id on the first reply and expects it
on every later one; a local program reads one line at a time from stdin. None
of those can be guessed from an endpoint, so this table declares it, and an
adapter with a multi-turn item and no declaration is a configuration error
rather than a single-turn fallback.

That last part is the point. A silent fallback would record the opener's
answer, file it under an item that declares three turns, and produce a bundle
whose `conversational_integrity` result is entirely UNVERIFIABLE — a suite
reporting that it could not see anything, about a recording that could have
seen everything, with nothing anywhere saying the recorder simply did not ask.

```toml
# A service that wants the conversation so far in the request body.
[adapter.conversation]
mode = "history"
history_pointer = "messages"      # where in [adapter.body] the history goes

# A service that hands out a session id and expects it back.
[adapter.conversation]
mode = "session"
session_pointer = "session.id"       # dotted path in the *response*
session_body_pointer = "session_id"  # dotted path in the *body*, later turns

# A local program that reads one line per turn.
[adapter.conversation]
mode = "lines"
```

The message envelope for `history` is declarable in full — `role_key`,
`content_key`, `user_role`, `assistant_role` — with defaults matching the
shape most chat APIs use. Defaults are a convenience; nothing here assumes a
target speaks any particular dialect, because a harness that silently assumed
one would produce evidence about a request the operator never wrote.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import AdapterError

MODE_HISTORY = "history"
MODE_SESSION = "session"
MODE_LINES = "lines"

#: Keys each mode understands. Anything else is refused rather than ignored,
#: the same rule the adapter tables follow: a misspelled key is a setting that
#: is not there, and here that means turns travelling in a shape nobody chose.
_KEYS_BY_MODE: dict[str, frozenset[str]] = {
    MODE_HISTORY: frozenset({
        "mode", "history_pointer", "role_key", "content_key", "user_role",
        "assistant_role",
    }),
    MODE_SESSION: frozenset({
        "mode", "session_pointer", "session_body_pointer",
    }),
    MODE_LINES: frozenset({"mode"}),
}


@dataclass(frozen=True)
class ConversationConfig:
    """A validated `[adapter.conversation]` table."""

    mode: str
    history_pointer: str = ""
    role_key: str = "role"
    content_key: str = "content"
    user_role: str = "user"
    assistant_role: str = "assistant"
    session_pointer: str = ""
    session_body_pointer: str = ""

    def describe(self) -> dict[str, Any]:
        """What the recorded manifest says about how the turns travelled.

        Recorded in full, not as the bare mode: a reader asking why turn two
        looked the way it did needs the envelope, and the envelope is exactly
        the part that differs between two targets both described as "history".
        """
        if self.mode == MODE_HISTORY:
            return {
                "mode": self.mode,
                "history_pointer": self.history_pointer,
                "role_key": self.role_key,
                "content_key": self.content_key,
                "user_role": self.user_role,
                "assistant_role": self.assistant_role,
            }
        if self.mode == MODE_SESSION:
            return {
                "mode": self.mode,
                "session_pointer": self.session_pointer,
                "session_body_pointer": self.session_body_pointer,
            }
        return {"mode": self.mode}

    def history_entries(
        self, turns: list[str], answers: list[str]
    ) -> list[dict[str, str]]:
        """The conversation so far, as the declared message envelope.

        ``turns`` and ``answers`` are the user turns already sent and the
        answers already received, so they are the same length: this is only
        ever called with completed exchanges.
        """
        entries: list[dict[str, str]] = []
        for asked, answered in zip(turns, answers):
            entries.append({self.role_key: self.user_role,
                            self.content_key: asked})
            entries.append({self.role_key: self.assistant_role,
                            self.content_key: answered})
        return entries


def _text(cfg: dict[str, Any], key: str, *, default: str = "",
          required: bool = False, why: str = "") -> str:
    value = cfg.get(key, default)
    if not isinstance(value, str) or (required and not value):
        raise AdapterError(
            f"[adapter.conversation].{key} must be a non-empty string"
            + (f": {why}" if why else "")
        )
    return value


def parse(raw: object, *, allowed_modes: tuple[str, ...],
          where: str) -> ConversationConfig:
    """Validate an `[adapter.conversation]` table for one adapter kind.

    ``allowed_modes`` is the adapter's own list: an HTTP target cannot carry
    turns as stdin lines and a local program has no session id to be handed,
    so each adapter names what it can actually do rather than accepting a mode
    it would then have to ignore.
    """
    if not isinstance(raw, dict) or not raw:
        raise AdapterError(
            f"[adapter.conversation] must be a table declaring how follow-up "
            f"turns reach the target (mode = "
            f"{' or '.join(repr(m) for m in allowed_modes)})"
        )
    mode = raw.get("mode")
    if mode not in allowed_modes:
        known = ", ".join(sorted(_KEYS_BY_MODE))
        raise AdapterError(
            f"[adapter.conversation].mode must be one of "
            f"{', '.join(repr(m) for m in allowed_modes)} for the {where} "
            f"adapter (got {mode!r}; modes this harness implements: {known})"
        )
    unknown = sorted(set(raw) - _KEYS_BY_MODE[mode])
    if unknown:
        raise AdapterError(
            f"[adapter.conversation] has key(s) mode = {mode!r} does not "
            f"understand: {', '.join(unknown)}. Refused rather than ignored — "
            f"a misspelled pointer is turns travelling somewhere nobody chose."
        )

    if mode == MODE_HISTORY:
        return ConversationConfig(
            mode=mode,
            history_pointer=_text(
                raw, "history_pointer", required=True,
                why="the dotted path in [adapter.body] where the "
                    "conversation so far is written, for example \"messages\""),
            role_key=_text(raw, "role_key", default="role", required=True),
            content_key=_text(raw, "content_key", default="content",
                              required=True),
            user_role=_text(raw, "user_role", default="user", required=True),
            assistant_role=_text(raw, "assistant_role", default="assistant",
                                 required=True),
        )
    if mode == MODE_SESSION:
        return ConversationConfig(
            mode=mode,
            session_pointer=_text(
                raw, "session_pointer", required=True,
                why="the dotted path in the target's *response* where the "
                    "session id appears on the first turn"),
            session_body_pointer=_text(
                raw, "session_body_pointer", required=True,
                why="the dotted path in [adapter.body] where that session id "
                    "is sent back on every later turn"),
        )
    return ConversationConfig(mode=mode)
