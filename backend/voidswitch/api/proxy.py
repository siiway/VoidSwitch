"""Public gateway endpoints — the OpenAI- and Anthropic-style inbound APIs.

Point an OpenAI client at ``/v1/chat/completions`` or Claude Code / an Anthropic
client at ``/v1/messages`` (set ANTHROPIC_BASE_URL to this server). Inbound and
upstream styles are translated transparently by the dispatcher.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from fnmatch import fnmatch

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import (
    CLIENT_HINT_HEADER,
    OPENCODE_CLIENT_HINT,
    SESSION_HEADER,
    UPSTREAM_UNAVAILABLE_STATUS,
    ApiStyle,
)
from voidswitch.core import auth
from voidswitch.core.database import get_session
from voidswitch.core.logging import get_logger, redact_headers
from voidswitch.models.db import ModelEntry, Provider, VoidToken
from voidswitch.services import models_catalog, role_groups, settings_store
from voidswitch.services.dispatcher import DispatchRequest, dispatch

router = APIRouter(tags=["gateway"])
log = get_logger("gateway")

# Lightweight in-process RPM limiter (sliding 60s window per token).
_rpm_window: dict[int, deque[float]] = defaultdict(deque)


def _check_rpm(token: VoidToken) -> None:
    if token.rpm_limit <= 0:
        return
    now = time.time()
    window = _rpm_window[token.id]
    cutoff = now - 60.0
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= token.rpm_limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Rate limit exceeded ({token.rpm_limit} req/min).",
        )
    window.append(now)


def _check_model_allowed(token: VoidToken, model: str) -> None:
    allowed = token.allowed_models or []
    if not allowed:
        return
    for pattern in allowed:
        if pattern == "*" or pattern == model or fnmatch(model, pattern):
            return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, f"Model '{model}' is not permitted for this token."
    )


async def _resolve_public_model(session: AsyncSession, model: str) -> str:
    """Map a public alias to its real upstream id; reject a hidden raw id.

    When an admin maps ``deepseek-v4`` → public ``ds``, callers must use ``ds``;
    ``ds`` resolves back to ``deepseek-v4`` for dispatch, and calling the raw
    ``deepseek-v4`` is rejected so the upstream id can't be reached directly.
    """
    alias_to_source, hidden_sources = await models_catalog.mapping_tables(session)
    if model in alias_to_source:
        return alias_to_source[model]
    if model in hidden_sources:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Model '{model}' is not available under this id.",
        )
    return model


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON body.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Request body must be a JSON object.")
    return data


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


async def _handle(
    request: Request,
    session: AsyncSession,
    authorization: str | None,
    x_api_key: str | None,
    inbound_style: ApiStyle,
) -> Response:
    authed = await auth.authenticate_void_token(session, authorization, x_api_key)
    payload = await _body(request)

    model = payload.get("model")
    if not isinstance(model, str) or not model:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing 'model'.")

    # Allow-list and rate-limit are checked against the *public* id the caller
    # used, then the model is resolved to its real upstream id (if it's an alias).
    _check_model_allowed(authed.token, model)
    _check_rpm(authed.token)
    model = await _resolve_public_model(session, model)
    payload["model"] = model

    # Role-group access: a non-moderator may only call models whose allowed role
    # groups intersect their own. Moderators may call everything.
    if not await role_groups.user_can_access_model(session, authed.user, model):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Model '{model}' is not available to your role group.",
        )

    stream = bool(payload.get("stream", False))
    passthrough: dict[str, str] = {}
    beta = request.headers.get("anthropic-beta")
    if beta and inbound_style is ApiStyle.ANTHROPIC:
        passthrough["anthropic-beta"] = beta

    # Verbose inbound tracing (debug mode only — gated by the log level so it
    # costs nothing when disabled). Credentials in the headers are masked.
    log.debug(
        "inbound_request",
        method=request.method,
        path=request.url.path,
        inbound_style=inbound_style.value,
        model=model,
        stream=stream,
        token_id=authed.token.id,
        client_ip=_client_ip(request),
        headers=redact_headers(request.headers),
        body=payload,
    )

    req = DispatchRequest(
        inbound_style=inbound_style,
        model=model,
        payload=payload,
        stream=stream,
        token_id=authed.token.id,
        user_sub=authed.user.sub,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        client_type=request.headers.get(CLIENT_HINT_HEADER),
        is_opencode=request.headers.get(CLIENT_HINT_HEADER) == OPENCODE_CLIENT_HINT,
        debug_enabled=authed.token.debug_enabled,
        passthrough_headers=passthrough,
        session_id=request.headers.get(SESSION_HEADER),
    )
    result = await dispatch(req)

    if result.is_stream and result.stream is not None:
        return StreamingResponse(
            result.stream,
            status_code=result.status_code,
            media_type=result.media_type,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    status_code = result.status_code
    # When no upstream could serve the request, swap the generic 502 ("Bad Gateway")
    # for a dedicated code — but only for the OpenCode plugin, which advertises itself
    # and knows how to render it as "Upstream Failed". Every other client keeps the
    # standard 502 so SDKs and intermediaries aren't surprised by a non-standard code.
    if (
        result.error == "upstream_unavailable"
        and request.headers.get(CLIENT_HINT_HEADER) == OPENCODE_CLIENT_HINT
    ):
        status_code = UPSTREAM_UNAVAILABLE_STATUS

    return Response(
        content=result.content or b"{}",
        status_code=status_code,
        media_type=result.media_type,
    )


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> Response:
    return await _handle(request, session, authorization, x_api_key, ApiStyle.OPENAI)


@router.post("/v1/messages")
async def messages(
    request: Request,
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> Response:
    return await _handle(request, session, authorization, x_api_key, ApiStyle.ANTHROPIC)


@router.get("/v1/models")
async def list_models(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> JSONResponse:
    authed = await auth.authenticate_void_token(session, authorization, x_api_key)
    token = authed.token

    providers = (
        (await session.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
    )
    # Per-model metadata (description + OpenCode config). A disabled entry hides
    # the model from the advertised list entirely.
    entries = {
        e.model_id: e for e in (await session.execute(select(ModelEntry))).scalars().all()
    }
    # Role-group access: moderators see every model; others only models whose
    # allowed role groups include one of theirs.
    is_mod = role_groups.is_moderator(authed.user)
    group_ids = set() if is_mod else await role_groups.user_group_ids(session, authed.user.id)
    seen: set[str] = set()
    data: list[dict[str, object]] = []
    allowed = token.allowed_models or []
    for provider in providers:
        # Raw upstream ids hidden behind alias routes must not be advertised;
        # only the alias (listed below via model_routes) is callable.
        hidden = models_catalog.routed_upstreams(provider)
        for model in provider.models or []:
            if model == "*" or model in hidden:
                continue
            entry = entries.get(model)
            if entry is not None and not entry.enabled:
                continue
            if not role_groups.model_allowed_for_groups(entry, group_ids, is_mod=is_mod):
                continue
            # Advertise (and accept) the public alias when one is set; the raw
            # upstream id is hidden so it never leaks and can't be called directly.
            public_id = entry.mapped_id if entry is not None and entry.mapped_id else model
            if public_id in seen:
                continue
            if allowed and not any(
                p == "*" or p == public_id or fnmatch(public_id, p) for p in allowed
            ):
                continue
            seen.add(public_id)
            item: dict[str, object] = {
                "id": public_id,
                "object": "model",
                "created": 0,
                "owned_by": provider.name,
            }
            if entry is not None:
                if entry.display_name:
                    item["display_name"] = entry.display_name
                if entry.description:
                    item["description"] = entry.description
                if entry.opencode_config:
                    # OpenCode plugin deep-merges this into the model block it builds.
                    item["opencode"] = entry.opencode_config
            data.append(item)
        # Also advertise alias-route models. Each alias gets a ModelEntry row
        # during sync, looked up by its alias name so mapped_id / description /
        # opencode_config still apply.
        for route in provider.model_routes or []:
            if not isinstance(route, dict):
                continue
            alias = route.get("alias")
            if not isinstance(alias, str) or not alias:
                continue
            entry = entries.get(alias)
            if entry is not None and not entry.enabled:
                continue
            if not role_groups.model_allowed_for_groups(entry, group_ids, is_mod=is_mod):
                continue
            # Skip if the alias's public id is already listed (e.g. alias also
            # appears as a raw model name on another provider, or the mapped_id
            # collides).
            public_id = entry.mapped_id if entry is not None and entry.mapped_id else alias
            if public_id in seen:
                continue
            if allowed and not any(
                p == "*" or p == public_id or fnmatch(public_id, p) for p in allowed
            ):
                continue
            seen.add(public_id)
            item: dict[str, object] = {
                "id": public_id,
                "object": "model",
                "created": 0,
                "owned_by": provider.name,
            }
            if entry is not None:
                if entry.display_name:
                    item["display_name"] = entry.display_name
                if entry.description:
                    item["description"] = entry.description
                if entry.opencode_config:
                    item["opencode"] = entry.opencode_config
            data.append(item)
    return JSONResponse({"object": "list", "data": data})


@router.post("/v1/models/sync")
async def sync_models(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> JSONResponse:
    """Refresh the platform model catalog from the providers (token-authed).

    Lets the OpenCode ``/models`` slash command keep the catalog in sync with
    what the providers currently serve. Only discovers already-served models, so
    it is safe to expose to any valid client token. Also returns the gateway's
    recommended OpenCode ``model`` / ``small_model`` selectors (bare model ids,
    same values as the public ``/api/auth/config`` endpoint) so the plugin can
    sync the top-level config keys alongside the provider's model map.
    """
    await auth.authenticate_void_token(session, authorization, x_api_key)
    added, total = await models_catalog.sync_from_providers(session)
    return JSONResponse(
        {
            "added": added,
            "total": total,
            "opencode_default_model": settings_store.get_str(
                "opencode_default_model", "claude-opus-4-8"
            ),
            "opencode_small_model": settings_store.get_str("opencode_small_model", ""),
        }
    )
