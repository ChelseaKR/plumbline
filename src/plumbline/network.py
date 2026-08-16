"""The only module in Plumbline that talks to the outside world.

Everything that opens a socket lives here: the live-target adapters and the
optional model-based judge both call through this module and nothing else
does. That is a deliberate architectural bound, and `tests/test_network.py`
enforces it by reading the source tree — the offline default is worth more
than a convenience import.

The client is bounded on purpose. An evaluation harness that hangs, follows a
redirect somewhere it was not pointed, or reads an unbounded response body is
not an instrument anyone should trust with a merge gate:

- **http and https only.** `urllib` will happily open `file://`; a target URL
  is configuration, and configuration should not be able to read the disk.
- **No redirects.** A target that redirects is a misconfiguration, not
  something to follow silently to an endpoint nobody declared.
- **No credentials in the URL.** They end up in logs and in provenance blocks.
  Secrets come from the environment, by name.
- **An explicit timeout, an explicit response-size ceiling, and retries off by
  default.** Every bound has a value in the recorded call shape, so a reader of
  a recorded bundle can see what the recorder was willing to wait for.

Nothing here is called during `plumbline audit` or `plumbline gate`.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import __version__
from .hashing import canonical_json, sha256_text

ALLOWED_SCHEMES = ("http", "https")
ALLOWED_METHODS = ("GET", "POST")

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_RESPONSE_BYTES = 262144  # 256 KiB
MAX_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_RETRIES = 5
MAX_RETRY_DELAY_SECONDS = 60.0
RETRYABLE_STATUS = (429, 500, 502, 503, 504)

USER_AGENT = f"plumbline/{__version__}"

# Header names whose value should come from the environment, not from a file
# somebody committed. Matching one with a literal value is a warning, never a
# refusal: it is not the harness's place to decide that a token is a secret,
# only to say out loud that it looks like one.
SECRET_HEADER_HINTS = ("authorization", "api-key", "x-api-key", "token",
                       "cookie", "secret")

PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


class OutboundError(Exception):
    """Base for every failure in this module (configuration error, exit 4)."""


class OutboundConfigError(OutboundError):
    """The declared call shape is unusable."""


class NetworkError(OutboundError):
    """The call was attempted and did not produce a usable response."""


# --- URLs -------------------------------------------------------------------

def check_endpoint(url: object) -> str:
    """Validate a configured endpoint URL, or refuse it with a reason."""
    if not isinstance(url, str) or not url.strip():
        raise OutboundConfigError("endpoint must be a non-empty URL string")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise OutboundConfigError(
            f"endpoint scheme '{parsed.scheme or '(none)'}' is not allowed; "
            f"Plumbline speaks {' and '.join(ALLOWED_SCHEMES)} only, because a "
            f"configured URL should not be able to read the filesystem"
        )
    if not parsed.hostname:
        raise OutboundConfigError(f"endpoint has no host: {url}")
    if parsed.username or parsed.password:
        raise OutboundConfigError(
            "endpoint carries credentials in the URL; put them in a header "
            "sourced from the environment instead, so they stay out of logs "
            "and out of recorded provenance"
        )
    return url


def public_endpoint(url: str) -> str:
    """The part of an endpoint safe to record: scheme, host, port, path.

    The query string is dropped rather than recorded. Plenty of APIs take a
    key there, and a manifest is committed evidence.
    """
    parsed = urllib.parse.urlsplit(url)
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}{parsed.path}"


def check_method(method: object) -> str:
    if not isinstance(method, str) or method.upper() not in ALLOWED_METHODS:
        raise OutboundConfigError(
            f"method must be one of {', '.join(ALLOWED_METHODS)} (got {method!r})"
        )
    return method.upper()


# --- Bounds -----------------------------------------------------------------

def _bounded_number(value, *, name, default, low, high, kind=float):
    if value is None:
        return kind(default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OutboundConfigError(f"{name} must be a number (got {value!r})")
    value = kind(value)
    if not (low <= value <= high):
        raise OutboundConfigError(f"{name} must be between {low} and {high} (got {value})")
    return value


@dataclass(frozen=True)
class Bounds:
    """What the caller is willing to wait for, read, and retry."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    retries: int = 0
    retry_delay_seconds: float = 0.0

    @classmethod
    def from_config(cls, cfg: dict) -> "Bounds":
        return cls(
            timeout_seconds=_bounded_number(
                cfg.get("timeout_seconds"), name="timeout_seconds",
                default=DEFAULT_TIMEOUT_SECONDS, low=0.1, high=MAX_TIMEOUT_SECONDS),
            max_response_bytes=_bounded_number(
                cfg.get("max_response_bytes"), name="max_response_bytes",
                default=DEFAULT_MAX_RESPONSE_BYTES, low=1,
                high=MAX_MAX_RESPONSE_BYTES, kind=int),
            retries=_bounded_number(
                cfg.get("retries"), name="retries", default=0, low=0,
                high=MAX_RETRIES, kind=int),
            retry_delay_seconds=_bounded_number(
                cfg.get("retry_delay_seconds"), name="retry_delay_seconds",
                default=0.0, low=0.0, high=MAX_RETRY_DELAY_SECONDS),
        )

    def as_config(self) -> dict:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
            "retries": self.retries,
            "retry_delay_seconds": self.retry_delay_seconds,
        }


# --- Headers ----------------------------------------------------------------

def resolve_headers(raw: object, *, where: str) -> tuple[dict[str, str], list[str]]:
    """Resolve configured headers, reading `{ env = "NAME" }` values from the
    environment. Returns (headers, warnings).

    A missing environment variable is a configuration error: the alternative
    is a run that quietly talks to a target unauthenticated and records
    whatever it gets back.
    """
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        raise OutboundConfigError(f"{where}: headers must be a table")
    headers: dict[str, str] = {}
    warnings: list[str] = []
    for name, value in raw.items():
        if isinstance(value, dict):
            var = value.get("env")
            if not isinstance(var, str) or not var:
                raise OutboundConfigError(
                    f"{where}: header '{name}' must be a string or "
                    f"{{ env = \"VARIABLE_NAME\" }}"
                )
            resolved = os.environ.get(var)
            if resolved is None:
                raise OutboundConfigError(
                    f"{where}: header '{name}' reads environment variable "
                    f"'{var}', which is not set"
                )
            headers[name] = resolved
        elif isinstance(value, str):
            if any(hint in name.lower() for hint in SECRET_HEADER_HINTS):
                warnings.append(
                    f"{where}: header '{name}' has a literal value in the "
                    f"configuration file; use {{ env = \"VARIABLE_NAME\" }} so "
                    f"the secret is not committed"
                )
            headers[name] = value
        else:
            raise OutboundConfigError(
                f"{where}: header '{name}' must be a string or "
                f"{{ env = \"VARIABLE_NAME\" }}"
            )
    return headers, warnings


# --- Request body templates -------------------------------------------------

def placeholders_in(template: object) -> set[str]:
    """Every `{placeholder}` appearing anywhere in a template."""
    found: set[str] = set()
    if isinstance(template, str):
        found.update(PLACEHOLDER_RE.findall(template))
    elif isinstance(template, dict):
        for value in template.values():
            found |= placeholders_in(value)
    elif isinstance(template, list):
        for value in template:
            found |= placeholders_in(value)
    return found


def fill_template(template: object, values: dict[str, str]) -> object:
    """Substitute `{placeholder}` occurrences inside a JSON-shaped template.

    Substitution happens in the template, never in the data, so a prompt
    containing a brace is inert. An unknown placeholder is a configuration
    error rather than a literal left in the request: a typo that ships the
    string `{prompot}` to a target would produce evidence of nothing.
    """
    if isinstance(template, str):
        def replace(match: re.Match) -> str:
            key = match.group(1)
            if key not in values:
                raise OutboundConfigError(
                    f"unknown placeholder '{{{key}}}' in the request template "
                    f"(available: {', '.join(sorted(values))})"
                )
            return values[key]
        return PLACEHOLDER_RE.sub(replace, template)
    if isinstance(template, dict):
        return {k: fill_template(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill_template(v, values) for v in template]
    return template


# --- Response pointers ------------------------------------------------------

def resolve_pointer(payload: object, pointer: str) -> object:
    """Read a value out of a decoded JSON response by dotted path.

    `choices.0.message.content` walks objects by key and arrays by index. A
    path that does not resolve is an error naming what was actually there:
    silently scoring an empty answer would turn a broken integration into a
    quality finding.
    """
    if not isinstance(pointer, str) or not pointer:
        raise OutboundConfigError("response_pointer must be a non-empty string")
    current = payload
    walked: list[str] = []
    for part in pointer.split("."):
        walked.append(part)
        here = ".".join(walked)
        if isinstance(current, dict):
            if part not in current:
                raise NetworkError(
                    f"response has no '{here}' (keys at that level: "
                    f"{', '.join(sorted(map(str, current))) or 'none'})"
                )
            current = current[part]
        elif isinstance(current, list):
            if not part.lstrip("-").isdigit():
                raise NetworkError(
                    f"response element at '{'.'.join(walked[:-1]) or '(root)'}' "
                    f"is a list; '{part}' is not an index"
                )
            index = int(part)
            if not (-len(current) <= index < len(current)):
                raise NetworkError(
                    f"response list at '{'.'.join(walked[:-1]) or '(root)'}' has "
                    f"{len(current)} element(s); index {index} is out of range"
                )
            current = current[index]
        else:
            raise NetworkError(
                f"response value at '{'.'.join(walked[:-1]) or '(root)'}' is "
                f"{type(current).__name__}, so '{part}' cannot be read from it"
            )
    return current


# --- The call ---------------------------------------------------------------

@dataclass(frozen=True)
class CallShape:
    """A declared, non-secret description of an outbound call.

    Header *names* are recorded; header values never are. The digest of this
    object goes into recorded provenance so two recordings made with the same
    call shape can be recognised as such.
    """

    url: str
    method: str = "POST"
    header_names: tuple[str, ...] = ()
    body_template: object = None
    response_pointer: str = ""
    bounds: Bounds = field(default_factory=Bounds)

    def as_config(self) -> dict:
        return {
            "endpoint": public_endpoint(self.url),
            "method": self.method,
            "header_names": sorted(self.header_names),
            "body_template": self.body_template,
            "response_pointer": self.response_pointer,
            "bounds": self.bounds.as_config(),
        }

    def digest(self) -> str:
        return sha256_text(canonical_json(self.as_config()))


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise NetworkError(
            f"the target redirected ({code}) to {newurl}; Plumbline does not "
            f"follow redirects, because an audit should talk to the endpoint "
            f"it was pointed at and no other"
        )


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def _snippet(raw: bytes, limit: int = 200) -> str:
    text = raw.decode("utf-8", errors="replace").strip().replace("\n", " ")
    return text[:limit] + ("…" if len(text) > limit else "")


def call_json(shape: CallShape, headers: dict[str, str], body: object,
              *, sleep=time.sleep) -> object:
    """Make one bounded call and return the decoded JSON response.

    Every failure raises NetworkError with a reason a human can act on. There
    is no path that returns a default, an empty string, or None.
    """
    data = None
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers)
    if shape.method == "POST":
        data = json.dumps(body if body is not None else {},
                          ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(
        shape.url, data=data, headers=request_headers, method=shape.method)

    attempts = shape.bounds.retries + 1
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with _OPENER.open(request, timeout=shape.bounds.timeout_seconds) as resp:
                raw = resp.read(shape.bounds.max_response_bytes + 1)
            if len(raw) > shape.bounds.max_response_bytes:
                raise NetworkError(
                    f"response exceeded max_response_bytes "
                    f"({shape.bounds.max_response_bytes}); refusing to grade a "
                    f"truncated answer"
                )
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise NetworkError(
                    f"target returned something that is not JSON ({e}): "
                    f"{_snippet(raw)}"
                ) from e
        except urllib.error.HTTPError as e:
            body_text = _snippet(e.read(shape.bounds.max_response_bytes))
            last = NetworkError(f"target returned HTTP {e.code}: {body_text}")
            if e.code not in RETRYABLE_STATUS or attempt == attempts:
                raise last from e
        except NetworkError:
            raise
        except urllib.error.URLError as e:
            last = NetworkError(f"could not reach {public_endpoint(shape.url)}: {e.reason}")
            if attempt == attempts:
                raise last from e
        except TimeoutError as e:
            last = NetworkError(
                f"{public_endpoint(shape.url)} did not answer within "
                f"{shape.bounds.timeout_seconds}s")
            if attempt == attempts:
                raise last from e
        if shape.bounds.retry_delay_seconds:
            sleep(shape.bounds.retry_delay_seconds)
    raise last or NetworkError("call failed for an unrecorded reason")
