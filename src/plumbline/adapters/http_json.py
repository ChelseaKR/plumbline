"""`http_json`: record against any target that answers a JSON POST.

Deliberately provider-neutral. The request body is a template written in the
target configuration and the answer is read out of the response by a dotted
path, so pointing Plumbline at a service means describing that service rather
than waiting for someone to write an integration for it:

```toml
[adapter]
kind = "http_json"
endpoint = "https://navigator.example.gov/api/chat"
response_pointer = "reply.text"
timeout_seconds = 20
min_interval_seconds = 0.5
max_items = 100

[adapter.headers]
Authorization = { env = "NAVIGATOR_TOKEN" }   # never written to the bundle

[adapter.body]
question = "{prompt}"
locale = "{lang}"
trace_id = "{item_id}"
```

Bounds live in `network.py`. The two bounds that belong here are the ones
about the *set* rather than the call: a minimum interval between requests, so
recording does not behave like a load test against a public service, and a
ceiling on how many items may be sent at all, so pointing the recorder at the
wrong question set costs one legible refusal instead of ten thousand requests.
"""

from __future__ import annotations

import time

from .. import network
from ..bundle import Item
from . import AdapterError

MAX_MIN_INTERVAL_SECONDS = 60.0
DEFAULT_MAX_ITEMS = 250
CEILING_MAX_ITEMS = 100_000

# The values a request template may interpolate. Anything else is a typo, and
# a typo that reached a live target would produce evidence of nothing.
TEMPLATE_KEYS = ("prompt", "lang", "item_id")

# Every key this adapter understands. An unrecognised key is refused rather
# than ignored: `timout_seconds` silently ignored is a bound that is not
# there, which is exactly the class of failure this harness exists to catch.
KNOWN_KEYS = frozenset({
    "kind", "questions", "endpoint", "method", "headers", "body",
    "response_pointer", "timeout_seconds", "max_response_bytes", "retries",
    "retry_delay_seconds", "min_interval_seconds", "max_items", "on_error",
})


class HttpJsonAdapter:
    kind = "http_json"

    def __init__(self, *, shape: network.CallShape, headers: dict[str, str],
                 min_interval_seconds: float, max_items: int,
                 on_error: str, sleep=time.sleep, clock=time.monotonic):
        self._shape = shape
        self._headers = headers
        self._min_interval = min_interval_seconds
        self.max_items = max_items
        self.on_error = on_error
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    # --- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict) -> tuple["HttpJsonAdapter", list[str]]:
        unknown_keys = sorted(set(cfg) - KNOWN_KEYS)
        if unknown_keys:
            raise AdapterError(
                f"[adapter] has key(s) the http_json adapter does not "
                f"understand: {', '.join(unknown_keys)}. Refused rather than "
                f"ignored — a misspelled bound is a bound that is not there."
            )
        try:
            url = network.check_endpoint(cfg.get("endpoint"))
            method = network.check_method(cfg.get("method", "POST"))
            bounds = network.Bounds.from_config(cfg)
            headers, warnings = network.resolve_headers(
                cfg.get("headers"), where="[adapter.headers]")
        except network.OutboundConfigError as e:
            raise AdapterError(f"[adapter]: {e}") from e

        if method != "POST":
            raise AdapterError(
                "[adapter]: the http_json adapter posts a JSON body, so "
                "method must be POST"
            )

        body = cfg.get("body")
        if not isinstance(body, dict) or not body:
            raise AdapterError(
                "[adapter.body] is required: it is the JSON body sent to the "
                "target, with {prompt} where the item's prompt goes"
            )
        unknown = sorted(network.placeholders_in(body) - set(TEMPLATE_KEYS))
        if unknown:
            raise AdapterError(
                f"[adapter.body] uses unknown placeholder(s) "
                f"{', '.join('{' + u + '}' for u in unknown)}; available: "
                f"{', '.join('{' + k + '}' for k in TEMPLATE_KEYS)}"
            )
        if "prompt" not in network.placeholders_in(body):
            raise AdapterError(
                "[adapter.body] never uses {prompt}, so every item would send "
                "the target the same request; that is not a recording"
            )

        pointer = cfg.get("response_pointer")
        if not isinstance(pointer, str) or not pointer:
            raise AdapterError(
                "[adapter].response_pointer is required: the dotted path to "
                "the answer text in the target's JSON response, for example "
                "\"reply\" or \"choices.0.message.content\""
            )

        min_interval = cfg.get("min_interval_seconds", 0.0)
        if (isinstance(min_interval, bool)
                or not isinstance(min_interval, (int, float))
                or not (0.0 <= min_interval <= MAX_MIN_INTERVAL_SECONDS)):
            raise AdapterError(
                f"[adapter].min_interval_seconds must be a number between 0 "
                f"and {MAX_MIN_INTERVAL_SECONDS}"
            )

        max_items = cfg.get("max_items", DEFAULT_MAX_ITEMS)
        if (isinstance(max_items, bool) or not isinstance(max_items, int)
                or not (1 <= max_items <= CEILING_MAX_ITEMS)):
            raise AdapterError(
                f"[adapter].max_items must be a whole number between 1 and "
                f"{CEILING_MAX_ITEMS} (default {DEFAULT_MAX_ITEMS}); it is the "
                f"guard against sending a question set nobody meant to send"
            )

        on_error = cfg.get("on_error", "abort")
        if on_error not in ("abort", "record_empty"):
            raise AdapterError(
                "[adapter].on_error must be \"abort\" (default: a failed call "
                "stops the recording) or \"record_empty\" (record an empty "
                "answer, which the smoke suite then fails on)"
            )

        shape = network.CallShape(
            url=url, method=method, header_names=tuple(headers),
            body_template=body, response_pointer=pointer, bounds=bounds,
        )
        return cls(shape=shape, headers=headers,
                   min_interval_seconds=float(min_interval),
                   max_items=max_items, on_error=on_error), warnings

    # --- provenance ---------------------------------------------------------

    def describe(self) -> dict:
        """What goes into the recorded bundle's manifest. Header names, never
        header values; endpoint without query string or credentials."""
        return {
            "kind": self.kind,
            "endpoint": network.public_endpoint(self._shape.url),
            "request_sha256": self._shape.digest(),
            "call": self._shape.as_config(),
            "min_interval_seconds": self._min_interval,
            "on_error": self.on_error,
        }

    # --- recording ----------------------------------------------------------

    def respond(self, item: Item) -> str:
        self._throttle()
        body = network.fill_template(self._shape.body_template, {
            "prompt": item.prompt,
            "lang": item.lang,
            "item_id": item.id,
        })
        try:
            payload = network.call_json(self._shape, self._headers, body)
            answer = network.resolve_pointer(payload, self._shape.response_pointer)
        except network.OutboundError as e:
            raise AdapterError(f"item '{item.id}': {e}") from e
        if not isinstance(answer, str):
            raise AdapterError(
                f"item '{item.id}': the value at "
                f"'{self._shape.response_pointer}' is "
                f"{type(answer).__name__}, not the answer text"
            )
        return answer

    def _throttle(self) -> None:
        if not self._min_interval:
            return
        now = self._clock()
        if self._last_call is not None:
            wait = self._min_interval - (now - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()
