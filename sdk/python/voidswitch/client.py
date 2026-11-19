"""The HTTP transport and the top-level :class:`Client`."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from .errors import InvalidRequestError, TransportError, error_for

DEFAULT_TIMEOUT = 30.0


class Client:
    """A platform API client bound to one deployment and one API key.

    :param base_url: Deployment root, e.g. ``https://voidswitch.example.com``.
        A trailing slash and a trailing ``/api/v1`` are both tolerated.
    :param api_key: A ``vsapi-…`` platform API key.
    :param timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        base = base_url.rstrip("/")
        for suffix in ("/api/v1", "/api"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        if not base:
            raise ValueError("base_url is required")
        self.base_url = base
        self.api_key = api_key
        self.timeout = timeout

        # Resource namespaces. They are plain attributes on the client so the
        # call sites read as vs.models.list() rather than vs.get("/models").
        from .resources import (
            Announcements,
            APIKeys,
            AuditLogs,
            Categories,
            Models,
            NodeGroups,
            Nodes,
            ProviderKeys,
            Providers,
            RequestLogs,
            RoleGroups,
            Settings,
            Stats,
            Users,
        )

        self.models = Models(self)
        self.categories = Categories(self)
        self.providers = Providers(self)
        self.provider_keys = ProviderKeys(self)
        self.nodes = Nodes(self)
        self.node_groups = NodeGroups(self)
        self.users = Users(self)
        self.role_groups = RoleGroups(self)
        self.api_keys = APIKeys(self)
        self.request_logs = RequestLogs(self)
        self.audit_logs = AuditLogs(self)
        self.announcements = Announcements(self)
        self.stats = Stats(self)
        self.settings = Settings(self)

    # -- low level ---------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Send one request and return the decoded JSON (``None`` when empty)."""
        url = self.base_url + "/api/v1" + path
        if params:
            query = {k: v for k, v in params.items() if v is not None}
            if query:
                url += "?" + urllib.parse.urlencode(query, doseq=True)

        data = None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            payload = _decode(exc.read())
            raise error_for(exc.code, f"HTTP {exc.code}", payload) from None
        except urllib.error.URLError as exc:
            raise TransportError(f"request to {url} failed: {exc.reason}") from None

        if not raw:
            return None
        return _decode(raw)

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, json_body=body if body is not None else {})

    def put(self, path: str, body: Any = None) -> Any:
        return self.request("PUT", path, json_body=body if body is not None else {})

    def patch(self, path: str, body: Any = None) -> Any:
        return self.request("PATCH", path, json_body=body if body is not None else {})

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # -- identity ----------------------------------------------------------

    def whoami(self) -> dict[str, Any]:
        """Return the key's owner, scopes and the actions it may call."""
        return self.get("/whoami")

    def __repr__(self) -> str:
        return f"Client({self.base_url!r})"


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.decode("utf-8", "replace")