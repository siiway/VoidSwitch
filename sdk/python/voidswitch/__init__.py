"""VoidSwitch Python SDK — REST and read helpers for the platform API.

The platform API is the automation surface of a VoidSwitch deployment. One
staff-owned API key (``vsapi-…``) drives both it and the MCP endpoint
``/api/v1/mcp``; the key's scopes decide what the caller may do.

    from voidswitch import Client

    vs = Client("https://voidswitch.example.com", api_key="vsapi-…")
    for model in vs.models.list():
        print(model["model_id"], model["enabled"])

Every call is one HTTP request to ``/api/v1``. Failures raise a subclass of
:class:`VoidSwitchError` carrying the server's message, so callers never have to
inspect response objects.
"""

from __future__ import annotations

from .client import Client
from .errors import (
    NotFoundError,
    PermissionError,
    RateLimitError,
    UnauthorizedError,
    VoidSwitchError,
)
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

__all__ = [
    "Client",
    "VoidSwitchError",
    "UnauthorizedError",
    "PermissionError",
    "NotFoundError",
    "RateLimitError",
    "Models",
    "Categories",
    "Providers",
    "ProviderKeys",
    "Nodes",
    "NodeGroups",
    "Users",
    "RoleGroups",
    "APIKeys",
    "RequestLogs",
    "AuditLogs",
    "Announcements",
    "Stats",
    "Settings",
]

__version__ = "0.1.0"
