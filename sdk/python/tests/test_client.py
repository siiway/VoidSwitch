"""Offline tests for the VoidSwitch Python SDK.

A tiny in-process HTTP server records each request and replays canned responses,
so the tests pin the path shapes and the error mapping without a deployment.
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from voidswitch import Client, NotFoundError, PermissionError, RateLimitError


class _Recorder(BaseHTTPRequestHandler):
    routes: dict[tuple[str, str], tuple[int, object]] = {}
    seen: list[dict] = []

    def _handle(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0]
        body = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            body = json.loads(self.rfile.read(length) or b"{}")
        _Recorder.seen.append(
            {
                "method": self.command,
                "path": path,
                "query": self.path.partition("?")[2],
                "auth": self.headers.get("Authorization"),
                "body": body,
            }
        )
        status, payload = _Recorder.routes.get((self.command, path), (404, {"detail": "not found"}))
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle

    def log_message(self, *args):  # silence the test output
        pass


class SDKTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), _Recorder)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def setUp(self) -> None:
        _Recorder.routes = {}
        _Recorder.seen = []
        self.client = Client(self.base + "/api/v1/", api_key="vsapi-test")

    def last(self) -> dict:
        self.assertTrue(_Recorder.seen, "no request was made")
        return _Recorder.seen[-1]

    def route(self, method: str, path: str, status: int, payload: object) -> None:
        _Recorder.routes[(method, path)] = (status, payload)

    def test_base_url_is_normalised(self) -> None:
        self.assertEqual(self.client.base_url, self.base)

    def test_models_delete_uses_public_id(self) -> None:
        self.route("DELETE", "/api/v1/models/fast-coder", 204, {})
        self.client.models.delete("fast-coder")
        self.assertEqual(self.last()["path"], "/api/v1/models/fast-coder")
        self.assertEqual(self.last()["auth"], "Bearer vsapi-test")

    def test_model_id_with_slash_is_one_segment(self) -> None:
        self.route("GET", "/api/v1/models/with%2Fslash", 200, {"model_id": "with/slash"})
        got = self.client.models.get("with/slash")
        self.assertEqual(got["model_id"], "with/slash")
        self.assertEqual(self.last()["path"], "/api/v1/models/with%2Fslash")

    def test_clear_cooldown_path(self) -> None:
        self.route(
            "POST", "/api/v1/models/fast-coder/route/upstreams/12/cooldown", 204, {}
        )
        self.client.models.clear_cooldown("fast-coder", 12)
        self.assertEqual(
            self.last()["path"], "/api/v1/models/fast-coder/route/upstreams/12/cooldown"
        )

    def test_provider_keys_address_the_slug(self) -> None:
        self.route("GET", "/api/v1/providers/by-slug/acme/keys", 200, [{"id": 1}])
        self.assertEqual(self.client.provider_keys.list("acme"), [{"id": 1}])
        self.assertEqual(self.last()["path"], "/api/v1/providers/by-slug/acme/keys")

    def test_provider_keys_add_may_omit_keys(self) -> None:
        self.route("POST", "/api/v1/providers/by-slug/acme/keys", 200, [])
        self.client.provider_keys.add("acme")
        self.assertEqual(self.last()["body"], {"keys": [], "pool": ""})

    def test_query_filters_are_forwarded(self) -> None:
        self.route("GET", "/api/v1/request-logs", 200, {"items": []})
        self.client.request_logs.list(limit=20, success=False, model=None)
        query = self.last()["query"]
        self.assertIn("limit=20", query)
        self.assertIn("success=False", query)
        self.assertNotIn("model", query)

    def test_error_mapping(self) -> None:
        self.route("DELETE", "/api/v1/providers/4", 403, {"detail": "missing scope"})
        with self.assertRaises(PermissionError) as ctx:
            self.client.providers.delete(4)
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.detail, "missing scope")

        self.route("GET", "/api/v1/models/nope", 404, {"detail": "Model not found."})
        with self.assertRaises(NotFoundError):
            self.client.models.get("nope")

        self.route("GET", "/api/v1/models", 429, {"detail": "rate limited"})
        with self.assertRaises(RateLimitError):
            self.client.models.list()

    def test_whoami(self) -> None:
        self.route("GET", "/api/v1/whoami", 200, {"scopes": ["read"], "tools": []})
        self.assertEqual(self.client.whoami()["scopes"], ["read"])


if __name__ == "__main__":
    unittest.main()