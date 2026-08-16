"""The bounded outbound HTTP client, exercised over real sockets.

Two things are under test here: that the bounds are real (they refuse, with a
reason, rather than doing the dangerous thing), and that the architectural
bound is real too — no module outside `network.py` opens a socket.
"""

from __future__ import annotations

import os
import threading
import unittest
from pathlib import Path

from helpers import LocalJSONServer, unused_url
from plumbline import network
from plumbline.hashing import canonical_json


def ok(payload):
    return lambda request: (200, payload)


class EndpointRules(unittest.TestCase):
    def test_http_and_https_only(self):
        for url in ("file:///etc/passwd", "ftp://example.test/x", "/no/scheme"):
            with self.assertRaises(network.OutboundConfigError) as ctx:
                network.check_endpoint(url)
            self.assertIn("not allowed", str(ctx.exception))

    def test_credentials_in_the_url_are_refused(self):
        with self.assertRaises(network.OutboundConfigError) as ctx:
            network.check_endpoint("https://user:secret@example.test/chat")
        self.assertIn("credentials", str(ctx.exception))

    def test_host_is_required(self):
        with self.assertRaises(network.OutboundConfigError):
            network.check_endpoint("http:///chat")

    def test_public_endpoint_drops_the_query_string(self):
        self.assertEqual(
            network.public_endpoint("https://example.test:8443/v1/chat?key=abc123"),
            "https://example.test:8443/v1/chat",
        )

    def test_method_must_be_get_or_post(self):
        self.assertEqual(network.check_method("post"), "POST")
        with self.assertRaises(network.OutboundConfigError):
            network.check_method("DELETE")


class BoundsRules(unittest.TestCase):
    def test_defaults_are_explicit(self):
        bounds = network.Bounds.from_config({})
        self.assertEqual(bounds.timeout_seconds, network.DEFAULT_TIMEOUT_SECONDS)
        self.assertEqual(bounds.retries, 0)

    def test_out_of_range_values_are_refused(self):
        for cfg in ({"timeout_seconds": 0}, {"timeout_seconds": 10_000},
                    {"retries": 99}, {"max_response_bytes": 0},
                    {"retry_delay_seconds": 600}):
            with self.assertRaises(network.OutboundConfigError):
                network.Bounds.from_config(cfg)

    def test_non_numeric_values_are_refused(self):
        with self.assertRaises(network.OutboundConfigError):
            network.Bounds.from_config({"timeout_seconds": "thirty"})


class HeaderResolution(unittest.TestCase):
    def test_values_can_come_from_the_environment(self):
        os.environ["PLUMBLINE_TEST_TOKEN"] = "shhh"
        self.addCleanup(os.environ.pop, "PLUMBLINE_TEST_TOKEN", None)
        headers, warnings = network.resolve_headers(
            {"X-Api-Key": {"env": "PLUMBLINE_TEST_TOKEN"}}, where="[adapter]")
        self.assertEqual(headers, {"X-Api-Key": "shhh"})
        self.assertEqual(warnings, [])

    def test_missing_environment_variable_is_an_error(self):
        os.environ.pop("PLUMBLINE_TEST_ABSENT", None)
        with self.assertRaises(network.OutboundConfigError) as ctx:
            network.resolve_headers(
                {"X-Api-Key": {"env": "PLUMBLINE_TEST_ABSENT"}}, where="[adapter]")
        self.assertIn("PLUMBLINE_TEST_ABSENT", str(ctx.exception))

    def test_a_literal_secret_warns_but_does_not_refuse(self):
        headers, warnings = network.resolve_headers(
            {"Authorization": "Bearer hunter2"}, where="[adapter]")
        self.assertEqual(headers["Authorization"], "Bearer hunter2")
        self.assertEqual(len(warnings), 1)
        self.assertIn("not committed", warnings[0])

    def test_a_plain_header_is_not_treated_as_a_secret(self):
        _, warnings = network.resolve_headers({"Accept-Language": "en"},
                                              where="[adapter]")
        self.assertEqual(warnings, [])

    def test_headers_must_be_a_table_of_strings(self):
        with self.assertRaises(network.OutboundConfigError):
            network.resolve_headers({"X": 5}, where="[adapter]")
        with self.assertRaises(network.OutboundConfigError):
            network.resolve_headers("nope", where="[adapter]")


class Templates(unittest.TestCase):
    def test_placeholders_are_found_at_any_depth(self):
        template = {"messages": [{"role": "user", "content": "{prompt}"}],
                    "meta": {"lang": "{lang}"}}
        self.assertEqual(network.placeholders_in(template), {"prompt", "lang"})

    def test_substitution_is_recursive(self):
        filled = network.fill_template(
            {"a": ["{prompt}", 3], "b": {"c": "in {lang}"}},
            {"prompt": "How much?", "lang": "es"})
        self.assertEqual(filled, {"a": ["How much?", 3], "b": {"c": "in es"}})

    def test_braces_in_the_data_are_inert(self):
        filled = network.fill_template({"q": "{prompt}"},
                                       {"prompt": "what is {this}?"})
        self.assertEqual(filled, {"q": "what is {this}?"})

    def test_an_unknown_placeholder_is_a_configuration_error(self):
        with self.assertRaises(network.OutboundConfigError) as ctx:
            network.fill_template({"q": "{prompot}"}, {"prompt": "x"})
        self.assertIn("prompot", str(ctx.exception))


class Pointers(unittest.TestCase):
    def test_walks_objects_and_arrays(self):
        payload = {"choices": [{"message": {"content": "hello"}}]}
        self.assertEqual(
            network.resolve_pointer(payload, "choices.0.message.content"), "hello")

    def test_missing_key_names_what_was_there(self):
        with self.assertRaises(network.NetworkError) as ctx:
            network.resolve_pointer({"reply": "hi"}, "answer")
        self.assertIn("reply", str(ctx.exception))

    def test_index_out_of_range(self):
        with self.assertRaises(network.NetworkError):
            network.resolve_pointer({"c": []}, "c.0")

    def test_scalar_cannot_be_walked(self):
        with self.assertRaises(network.NetworkError):
            network.resolve_pointer({"reply": "hi"}, "reply.text")

    def test_pointer_must_be_a_non_empty_string(self):
        with self.assertRaises(network.OutboundConfigError):
            network.resolve_pointer({}, "")


class Calls(unittest.TestCase):
    def shape(self, url, **kw):
        bounds = network.Bounds.from_config(kw.pop("bounds", {}))
        return network.CallShape(url=url, method=kw.pop("method", "POST"),
                                 bounds=bounds, **kw)

    def test_a_real_round_trip(self):
        with LocalJSONServer(ok({"reply": "the cap is 850 dollars"})) as server:
            payload = network.call_json(
                self.shape(server.url + "/chat"), {"X-Test": "1"},
                {"question": "how much?"})
        self.assertEqual(payload["reply"], "the cap is 850 dollars")
        self.assertEqual(server.requests[0]["body"], {"question": "how much?"})
        self.assertEqual(server.requests[0]["headers"]["X-Test"], "1")
        self.assertTrue(
            server.requests[0]["headers"]["User-Agent"].startswith("plumbline/"))

    def test_unreachable_target_is_a_named_failure(self):
        with self.assertRaises(network.NetworkError) as ctx:
            network.call_json(self.shape(unused_url()), {}, {})
        self.assertIn("could not reach", str(ctx.exception))

    def test_http_error_carries_the_status_and_a_snippet(self):
        with LocalJSONServer(lambda r: (403, {"error": "no"})) as server:
            with self.assertRaises(network.NetworkError) as ctx:
                network.call_json(self.shape(server.url), {}, {})
        self.assertIn("HTTP 403", str(ctx.exception))
        self.assertEqual(len(server.requests), 1, "403 must not be retried")

    def test_retries_only_the_retryable_statuses(self):
        state = {"calls": 0}

        def flaky(request):
            state["calls"] += 1
            if state["calls"] == 1:
                return 503, {"error": "warming up"}
            return 200, {"reply": "ready"}

        with LocalJSONServer(flaky) as server:
            payload = network.call_json(
                self.shape(server.url, bounds={"retries": 2}), {}, {})
        self.assertEqual(payload, {"reply": "ready"})
        self.assertEqual(state["calls"], 2)

    def test_retries_are_bounded_and_then_it_gives_up(self):
        with LocalJSONServer(lambda r: (503, {"error": "down"})) as server:
            with self.assertRaises(network.NetworkError):
                network.call_json(
                    self.shape(server.url, bounds={"retries": 1}), {}, {})
            self.assertEqual(len(server.requests), 2)

    def test_non_json_is_refused(self):
        with LocalJSONServer(lambda r: (200, b"<html>hello</html>")) as server:
            with self.assertRaises(network.NetworkError) as ctx:
                network.call_json(self.shape(server.url), {}, {})
        self.assertIn("not JSON", str(ctx.exception))

    def test_oversized_response_is_refused_rather_than_truncated(self):
        big = {"reply": "x" * 5000}
        with LocalJSONServer(ok(big)) as server:
            with self.assertRaises(network.NetworkError) as ctx:
                network.call_json(
                    self.shape(server.url, bounds={"max_response_bytes": 100}),
                    {}, {})
        self.assertIn("max_response_bytes", str(ctx.exception))

    def test_redirects_are_refused(self):
        with LocalJSONServer(lambda r: (302, {})) as server:
            with self.assertRaises(network.NetworkError) as ctx:
                network.call_json(self.shape(server.url), {}, {})
        self.assertIn("redirect", str(ctx.exception))

    def test_timeout_is_reported_as_a_timeout(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def slow(request):
            release.wait(timeout=5)
            return 200, {"reply": "eventually"}

        with LocalJSONServer(slow) as server:
            with self.assertRaises(network.NetworkError) as ctx:
                network.call_json(
                    self.shape(server.url, bounds={"timeout_seconds": 0.2}), {}, {})
            release.set()
        self.assertIn("did not answer", str(ctx.exception))

    def test_get_sends_no_body(self):
        with LocalJSONServer(ok({"reply": "hi"})) as server:
            network.call_json(self.shape(server.url, method="GET"), {}, None)
        self.assertEqual(server.requests[0]["method"], "GET")
        self.assertEqual(server.requests[0]["raw"], b"")


class CallShapeProvenance(unittest.TestCase):
    def test_header_values_are_never_recorded(self):
        shape = network.CallShape(
            url="https://example.test/v1/chat?key=abc",
            header_names=("Authorization", "Content-Type"),
            body_template={"q": "{prompt}"}, response_pointer="reply")
        recorded = shape.as_config()
        self.assertEqual(recorded["endpoint"], "https://example.test/v1/chat")
        self.assertEqual(recorded["header_names"], ["Authorization", "Content-Type"])
        self.assertNotIn("abc", canonical_json(recorded))

    def test_digest_is_stable_and_shape_sensitive(self):
        a = network.CallShape(url="https://example.test/x",
                              body_template={"q": "{prompt}"},
                              response_pointer="reply")
        b = network.CallShape(url="https://example.test/x",
                              body_template={"q": "{prompt}"},
                              response_pointer="reply")
        c = network.CallShape(url="https://example.test/x",
                              body_template={"q": "{prompt}", "temp": 0.0},
                              response_pointer="reply")
        self.assertEqual(a.digest(), b.digest())
        self.assertNotEqual(a.digest(), c.digest())


class TheNetworkBoundaryIsArchitectural(unittest.TestCase):
    """Only one module is allowed to open a socket."""

    NETWORK_IMPORTS = ("urllib.request", "urllib.error", "http.client",
                       "socket", "requests", "httpx")

    def test_no_other_module_imports_a_network_library(self):
        package = Path(__file__).resolve().parent.parent / "src" / "plumbline"
        offenders = []
        for path in sorted(package.rglob("*.py")):
            if path.name == "network.py":
                continue
            text = path.read_text(encoding="utf-8")
            for name in self.NETWORK_IMPORTS:
                if f"import {name}" in text:
                    offenders.append(f"{path.name} imports {name}")
        self.assertEqual(
            offenders, [],
            "the offline default depends on network access living in exactly "
            "one module: " + "; ".join(offenders))


if __name__ == "__main__":
    unittest.main()
