"""Executing-user context for a manual token refresh.

When an operator clicks "refresh token" on a key, the OAuth token-endpoint call
(and its :class:`~voidswitch.models.db.RequestLog` row) should carry *who* asked
for it. The refresh happens deep inside the provider adapter → ``oauth_tokens`` /
``xai_oauth`` resolvers, so rather than thread an actor argument through every
layer we stash it in a :class:`contextvars.ContextVar` for the duration of the
call. The token-endpoint logger reads it when present; the automatic
near-expiry / 401-retry refreshes on the request path leave it unset and log
anonymously as before.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(slots=True)
class RefreshActor:
    """Who triggered a manual refresh, plus the key/provider it targeted."""

    actor_sub: str | None = None
    actor_name: str | None = None
    key_id: int | None = None
    provider_id: int | None = None
    provider_name: str | None = None
    user_agent: str | None = None


_current: contextvars.ContextVar[RefreshActor | None] = contextvars.ContextVar(
    "voidswitch_refresh_actor", default=None
)


def set_actor(actor: RefreshActor | None) -> contextvars.Token[RefreshActor | None]:
    """Bind the current manual-refresh actor; returns a token to reset with."""
    return _current.set(actor)


def get_actor() -> RefreshActor | None:
    """The manual-refresh actor in scope, or ``None`` on the automatic path."""
    return _current.get()


def reset(token: contextvars.Token[RefreshActor | None]) -> None:
    _current.reset(token)
