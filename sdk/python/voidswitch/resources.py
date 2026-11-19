"""Typed resource namespaces over the platform API.

Each class wraps one path prefix. Methods take and return plain JSON
(dicts/lists), so the SDK never needs a schema mirror of the backend and cannot
fall behind a server-side field addition.
"""

from __future__ import annotations

from typing import Any


class _Resource:
    def __init__(self, client) -> None:
        self._c = client


class Models(_Resource):
    """Exposed models and their routing plans (scope ``model.*``)."""

    def list(self) -> list[dict[str, Any]]:
        return self._c.get("/models")

    def get(self, model_id: str) -> dict[str, Any]:
        return self._c.get(f"/models/{_q(model_id)}")

    def upsert(self, model_id: str, **fields: Any) -> dict[str, Any]:
        body = {"model_id": model_id, **fields}
        return self._c.put("/models", body)

    def batch(self, model_ids: list[str], **fields: Any) -> dict[str, Any]:
        return self._c.post("/models/batch", {"model_ids": model_ids, **fields})

    def delete(self, model_id: str) -> None:
        self._c.delete(f"/models/{_q(model_id)}")

    def get_route(self, model_id: str) -> dict[str, Any]:
        return self._c.get(f"/models/{_q(model_id)}/route")

    def put_route(self, model_id: str, **fields: Any) -> dict[str, Any]:
        return self._c.put(f"/models/{_q(model_id)}/route", fields)

    def clear_cooldown(self, model_id: str, upstream_id: int) -> dict[str, Any]:
        """Clear one route upstream's cooldown."""
        return self._c.post(
            f"/models/{_q(model_id)}/route/upstreams/{upstream_id}/cooldown"
        )


class Categories(_Resource):
    """Model categories (scope ``category.*``)."""

    def list(self) -> list[dict[str, Any]]:
        return self._c.get("/model-categories")

    def create(self, name: str, position: int = 0) -> dict[str, Any]:
        return self._c.post("/model-categories", {"name": name, "position": position})


class Providers(_Resource):
    """Providers (scope ``provider.*``). Secrets are always redacted."""

    def list(self) -> list[dict[str, Any]]:
        return self._c.get("/providers")

    def get(self, provider_id: int) -> dict[str, Any]:
        return self._c.get(f"/providers/{provider_id}")

    def create(self, name: str, type: str, **fields: Any) -> dict[str, Any]:
        """Create a provider. Keys are optional; add them with ``provider_keys``."""
        return self._c.post("/providers", {"name": name, "type": type, **fields})

    def delete(self, provider_id: int) -> None:
        self._c.delete(f"/providers/{provider_id}")


class ProviderKeys(_Resource):
    """Upstream keys of one provider, addressed by provider slug.

    The key's scope must name the slug (``provider-key:<slug>.*``), which is why
    this resource takes a slug rather than an id.
    """

    def list(self, slug: str) -> list[dict[str, Any]]:
        return self._c.get(f"/providers/by-slug/{_q(slug)}/keys")

    def add(
        self,
        slug: str,
        keys: list[str] | None = None,
        *,
        pool: str = "",
        note: str | None = None,
    ) -> list[dict[str, Any]]:
        """Add upstream keys. An empty list is accepted and changes nothing."""
        body: dict[str, Any] = {"keys": keys or [], "pool": pool}
        if note is not None:
            body["note"] = note
        return self._c.post(f"/providers/by-slug/{_q(slug)}/keys", body)

    def update(self, slug: str, key_id: int, **fields: Any) -> dict[str, Any]:
        return self._c.patch(f"/providers/by-slug/{_q(slug)}/keys/{key_id}", fields)

    def delete(self, slug: str, key_id: int) -> None:
        self._c.delete(f"/providers/by-slug/{_q(slug)}/keys/{key_id}")

    def reorder(self, slug: str, ids: list[int]) -> dict[str, Any]:
        return self._c.post(f"/providers/by-slug/{_q(slug)}/keys/reorder", {"ids": ids})

    def refresh_balance(self, slug: str) -> dict[str, Any]:
        return self._c.post(f"/providers/by-slug/{_q(slug)}/keys/refresh-balance")

    def cleanup(self, slug: str, target: str = "insufficient_balance", min_days: int = 0) -> dict[str, Any]:
        body = {"target": target, "min_days": min_days}
        return self._c.post(f"/providers/by-slug/{_q(slug)}/keys/cleanup", body)


class Nodes(_Resource):
    """Egress nodes (scope ``node.*``)."""

    def list(self) -> list[dict[str, Any]]:
        return self._c.get("/nodes")

    def get(self, node_id: int) -> dict[str, Any]:
        return self._c.get(f"/nodes/{node_id}")

    def create(self, url: str, type: str = "http", **fields: Any) -> dict[str, Any]:
        return self._c.post("/nodes", {"url": url, "type": type, **fields})

    def delete(self, node_id: int) -> None:
        self._c.delete(f"/nodes/{node_id}")

    def probe(self, node_id: int) -> dict[str, Any]:
        return self._c.post(f"/nodes/{node_id}/probe")


class NodeGroups(_Resource):
    """Node groups (scope ``node-group.*``)."""

    def create(self, name: str, **fields: Any) -> dict[str, Any]:
        return self._c.post("/node-groups", {"name": name, **fields})


class Users(_Resource):
    """Users (scope ``user.*``)."""

    def list(self) -> list[dict[str, Any]]:
        return self._c.get("/users")

    def get(self, user_id: int) -> dict[str, Any]:
        return self._c.get(f"/users/{user_id}")

    def update(self, user_id: int, **fields: Any) -> dict[str, Any]:
        return self._c.patch(f"/users/{user_id}", fields)

    def force_logout(self, user_id: int) -> dict[str, Any]:
        return self._c.post(f"/users/{user_id}/force-logout")


class RoleGroups(_Resource):
    """Role groups (scope ``role-group.*``)."""

    def list(self) -> list[dict[str, Any]]:
        return self._c.get("/role-groups")

    def get(self, group_id: int) -> dict[str, Any]:
        return self._c.get(f"/role-groups/{group_id}")

    def create(self, name: str, **fields: Any) -> dict[str, Any]:
        return self._c.post("/role-groups", {"name": name, **fields})

    def delete(self, group_id: int) -> None:
        self._c.delete(f"/role-groups/{group_id}")

    def members(self, group_id: int) -> list[dict[str, Any]]:
        return self._c.get(f"/role-groups/{group_id}/members")

    def remove_member(self, group_id: int, user_id: int) -> None:
        self._c.delete(f"/role-groups/{group_id}/members/{user_id}")


class APIKeys(_Resource):
    """Platform API keys themselves (scope ``api-key.*``). Secrets are never
    returned by any of these calls except :meth:`rotate`."""

    def list(self) -> list[dict[str, Any]]:
        return self._c.get("/api-keys")

    def get(self, key_id: int) -> dict[str, Any]:
        return self._c.get(f"/api-keys/{key_id}")

    def update(self, key_id: int, **fields: Any) -> dict[str, Any]:
        return self._c.patch(f"/api-keys/{key_id}", fields)

    def delete(self, key_id: int) -> None:
        self._c.delete(f"/api-keys/{key_id}")

    def rotate(self, key_id: int) -> dict[str, Any]:
        """Rotate a key. The response carries the new secret exactly once."""
        return self._c.post(f"/api-keys/{key_id}/rotate")


class RequestLogs(_Resource):
    """Gateway request logs (scope ``request-log.*``)."""

    def list(self, **filters: Any) -> dict[str, Any]:
        return self._c.get("/request-logs", **filters)

    def get(self, log_id: int) -> dict[str, Any]:
        return self._c.get(f"/request-logs/{log_id}")

    def get_debug(self, log_id: int) -> dict[str, Any]:
        """Full failover trail for one request (bodies only for owners)."""
        return self._c.get(f"/request-logs/{log_id}/debug")

    def filters(self) -> dict[str, Any]:
        return self._c.get("/request-logs/filters")


class AuditLogs(_Resource):
    """Audit records (scope ``audit-log.*``). Reveal is deliberately absent."""

    def list(self, **filters: Any) -> dict[str, Any]:
        return self._c.get("/audit-logs", **filters)

    def filters(self) -> dict[str, Any]:
        return self._c.get("/audit-logs/filters")


class Announcements(_Resource):
    """Announcements (scope ``announcement.*``)."""

    def list(self) -> list[dict[str, Any]]:
        return self._c.get("/announcements")

    def create(self, title: str, body: str = "", target_role_group_ids: list[int] | None = None) -> dict[str, Any]:
        return self._c.post(
            "/announcements",
            {"title": title, "body": body, "target_role_group_ids": target_role_group_ids or []},
        )

    def delete(self, announcement_id: int) -> None:
        self._c.delete(f"/announcements/{announcement_id}")


class Stats(_Resource):
    """Dashboard counters (scope ``stats.get``)."""

    def get(self) -> dict[str, Any]:
        return self._c.get("/stats")


class Settings(_Resource):
    """Runtime settings (scope ``setting.get`` / ``setting.edit``)."""

    def get(self) -> dict[str, Any]:
        return self._c.get("/settings")

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._c.put("/settings", {"values": values})


def _q(value: str) -> str:
    """Quote one path segment, so a model id containing "/" still addresses one
    resource."""
    from urllib.parse import quote

    return quote(str(value), safe="")