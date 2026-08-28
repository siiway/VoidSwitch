"""Public gateway endpoints — the OpenAI- and Anthropic-style inbound APIs.

Point an OpenAI client at ``/v1/chat/completions`` (Chat Completions) or
``/v1/responses`` (the Responses API), or Claude Code / an Anthropic client at
``/v1/messages`` (set ANTHROPIC_BASE_URL to this server). Inbound and upstream
styles are translated transparently by the dispatcher.
"""

from __future__ import annotations

import datetime as dt
import re
from fnmatch import fnmatch

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import (
    CLIENT_HINT_HEADER,
    OPENCODE_CLIENT_HINT,
    SESSION_HEADER,
    UPSTREAM_UNAVAILABLE_STATUS,
    ApiStyle,
)
from voidswitch.core import auth, ratelimit
from voidswitch.core.database import get_session
from voidswitch.core.logging import get_logger, redact_headers
from voidswitch.models.db import ExposedModel, Provider, RequestLog, VoidToken
from voidswitch.services import model_routing, role_groups, settings_store
from voidswitch.services.dispatcher import DispatchRequest, dispatch

router = APIRouter(tags=["gateway"])
log = get_logger("gateway")


_PASSTHROUGH_RE = re.compile(
    r"^(?P<exposed>[^\s@]+?)(?:\s*=>\s*(?P<upstream>[^\s@]+?))?(?:\s*@\s*(?P<pool>\S+))?$"
)


def _parse_passthrough_entry(entry: str) -> dict[str, str]:
    """Parse a passthrough whitelist entry into its components."""
    m = _PASSTHROUGH_RE.match(entry.strip())
    if m is None:
        return {"exposed": entry.strip(), "upstream": entry.strip(), "pool": ""}
    exposed = (m.group("exposed") or "").strip()
    upstream = (m.group("upstream") or exposed).strip()
    pool = (m.group("pool") or "").strip()
    return {"exposed": exposed, "upstream": upstream, "pool": pool}


def _check_rpm(token: VoidToken) -> None:
    """Enforce a Void-Token's per-minute request cap (sliding 60s window).

    Backed by the shared, single-node :data:`ratelimit.gateway_rpm_limiter` — see
    that module's note on the multi-worker caveat (counters are per-process).
    """
    if token.rpm_limit <= 0:
        return
    if not ratelimit.gateway_rpm_limiter.allow(
        f"rpm:{token.id}", window_seconds=60.0, max_requests=token.rpm_limit
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Rate limit exceeded ({token.rpm_limit} req/min).",
        )


async def _check_daily_quota(session: AsyncSession, token: VoidToken) -> None:
    """Enforce a Void-Token's per-UTC-day request cap (``daily_quota``).

    Counts today's logged requests for the token (the same rows the request-log
    browser shows). 0 = unlimited.
    """
    if token.daily_quota <= 0:
        return
    start_of_day = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = (
        await session.execute(
            select(func.count(RequestLog.id)).where(
                RequestLog.token_id == token.id, RequestLog.ts >= start_of_day
            )
        )
    ).scalar_one()
    if used >= token.daily_quota:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Daily request quota exceeded ({token.daily_quota} requests/day).",
        )


def _check_call_rate_limit(user_id: int) -> None:
    """Per-user abuse limit on the OpenAI/Anthropic gateway endpoints.

    Independent of a token's own ``rpm_limit`` — this is a platform-wide guard
    that everyone obeys (owners included), counted per user. Disabled when the
    configured max is 0.
    """
    window = settings_store.get_int("call_rate_limit_window_seconds", 60)
    max_requests = settings_store.get_int("call_rate_limit_max_requests", 0)
    if not ratelimit.call_limiter.allow(
        f"call:{user_id}", window_seconds=window, max_requests=max_requests
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Call rate limit exceeded ({max_requests} per {window}s). Slow down.",
        )


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
    """Map a public model id to its exposed-model row.

    Only *exposed* ids are callable. Raw upstream ids (``slug/model``) are never
    advertised and are rejected here, so an upstream id can't be reached
    directly.

    Supports passthrough: when the model is in ``provider-slug/exposed-model-id``
    format, the provider is looked up and its passthrough whitelist is checked.
    """
    parts = model.split("/", 1)
    if len(parts) == 2:
        provider_slug = parts[0]
        exposed_id = parts[1]
        provider = (
            await session.execute(select(Provider).where(Provider.slug == provider_slug))
        ).scalar_one_or_none()
        if provider is not None and provider.enabled and provider.passthrough_enabled:
            for entry in provider.passthrough_models or []:
                parsed = _parse_passthrough_entry(entry)
                if parsed["exposed"] == exposed_id:
                    return model
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Model '{model}' is not in this provider's passthrough list.",
            )
    entry = (
        await session.execute(select(ExposedModel).where(ExposedModel.model_id == model))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Model '{model}' is not available under this id.",
        )
    if not entry.enabled:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Model '{model}' is not available under this id.",
        )
    return entry.model_id


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
    # Platform-wide per-user call rate limit (abuse guard, everyone incl. owners).
    _check_call_rate_limit(authed.user.id)
    payload = await _body(request)

    model = payload.get("model")
    if not isinstance(model, str) or not model:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing 'model'.")

    # A request body in the wrong shape (e.g. ``messages`` a string instead of a
    # list) would crash the translator later as a 500 after upstream billing;
    # reject it up front as a 400.
    for field in ("messages", "tools", "input"):
        if (
            field in payload
            and payload[field] is not None
            and not isinstance(payload[field], (list, str) if field == "input" else list)
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{field}' must be a list.")

    # Allow-list and rate-limit are checked against the *public* id the caller
    # used, then the model is resolved to its real upstream id (if it's an alias).
    _check_model_allowed(authed.token, model)
    _check_rpm(authed.token)
    await _check_daily_quota(session, authed.token)
    model = await _resolve_public_model(session, model)
    payload["model"] = model

    # Role-group access: a non-moderator may only call models whose allowed role
    # groups intersect their own. Moderators may call everything. Passthrough
    # models (``provider-slug/exposed-model-id``) are whitelist-controlled by the
    # provider and skip the role-group check.
    if "/" not in model and not await role_groups.user_can_access_model(
        session, authed.user, model
    ):
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
    result = await dispatch(req, session=session)

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


@router.post("/v1/responses")
async def responses(
    request: Request,
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> Response:
    return await _handle(request, session, authorization, x_api_key, ApiStyle.OPENAI_RESPONSES)


async def _advertised_models(
    session: AsyncSession, authed: auth.AuthedToken
) -> list[dict[str, object]]:
    """Models this caller may actually use, in ``/v1/models`` payload shape.

    Only *exposed* models are advertised (upstream ``slug/model`` ids never are).
    Role-group access is enforced (moderators see everything; others only models
    their groups allow), and the token's ``allowed_models`` allow-list is
    honoured. The ``opencode`` block is the fully merged downstream config
    (defaults ← models.dev placeholder ← custom config ← structured fields).

    Passthrough models from providers with ``passthrough_enabled=True`` are also
    listed as ``provider-slug/exposed-model-id``.
    """
    token = authed.token

    entries = (await session.execute(select(ExposedModel))).scalars().all()

    is_mod = role_groups.is_moderator(authed.user)
    group_ids = set() if is_mod else await role_groups.user_group_ids(session, authed.user.id)
    seen: set[str] = set()
    data: list[dict[str, object]] = []
    allowed = token.allowed_models or []

    # Pre-load the models.dev entries referenced by any exposed model, once.
    dev_ids = [e.models_dev_id for e in entries if e.models_dev_id]
    md_by_id: dict[str, dict] = {}
    if dev_ids:
        from sqlalchemy import select as _select

        from voidswitch.models.db import ModelsDevCache

        rows = (
            (await session.execute(_select(ModelsDevCache).where(ModelsDevCache.id.in_(dev_ids))))
            .scalars()
            .all()
        )
        md_by_id = {r.id: r.data or {} for r in rows}

    def _push(entry: ExposedModel) -> None:
        nonlocal data, seen, allowed, group_ids, is_mod, md_by_id
        if not entry.enabled:
            return
        if not role_groups.model_allowed_for_groups(entry, group_ids, is_mod=is_mod):
            return
        model_id = entry.model_id
        if model_id in seen:
            return
        if allowed and not any(
            pattern == "*" or pattern == model_id or fnmatch(model_id, pattern)
            for pattern in (str(p) for p in allowed)
        ):
            return
        seen.add(model_id)
        item: dict[str, object] = {
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "voidswitch",
        }
        # Downstream config: never advertise upstream refs.
        dev_entry = md_by_id.get(entry.models_dev_id) if entry.models_dev_id else None
        item["opencode"] = model_routing.build_opencode_config(entry, dev_entry)
        if entry.display_name:
            item["display_name"] = entry.display_name
        if entry.description:
            item["description"] = entry.description
        data.append(item)

    for entry in entries:
        _push(entry)

    # Passthrough models: each provider with passthrough_enabled contributes its
    # whitelisted models as ``provider-slug/exposed-model-id``.
    passthrough_providers = (
        (
            await session.execute(
                select(Provider).where(
                    Provider.enabled.is_(True), Provider.passthrough_enabled.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    for provider in passthrough_providers:
        for entry in provider.passthrough_models or []:
            parsed = _parse_passthrough_entry(entry)
            exposed_id = parsed["exposed"]
            model_id = f"{provider.slug}/{exposed_id}"
            if model_id in seen:
                continue
            if allowed and not any(
                pattern == "*" or pattern == model_id or fnmatch(model_id, pattern)
                for pattern in (str(p) for p in allowed)
            ):
                continue
            seen.add(model_id)
            data.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "voidswitch",
                }
            )

    return data


@router.get("/v1/models")
async def list_models(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> JSONResponse:
    authed = await auth.authenticate_void_token(session, authorization, x_api_key)
    data = await _advertised_models(session, authed)
    return JSONResponse({"object": "list", "data": data})


@router.post("/v1/models/sync")
async def sync_models(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> JSONResponse:
    """Report the models the caller can use (OpenCode ``/sync-models`` command).

    Open to **any** authenticated Void-Token, members included: it returns the
    exact set of models that token may call — role-group access and the token's
    allow-list applied, hidden/disabled models excluded — so the OpenCode plugin
    can refresh its provider model map to what the *user* actually has.

    It deliberately does **not** reshape the shared platform catalog; that is the
    staff-only "sync from providers" action on the dashboard
    (``POST /api/models/sync``). Keeping the two apart means a member's sync never
    needs admin rights. Also returns the gateway's recommended OpenCode
    ``model`` / ``small_model`` selectors so the plugin can sync the top-level
    config keys alongside the provider's model map.
    """
    authed = await auth.authenticate_void_token(session, authorization, x_api_key)
    data = await _advertised_models(session, authed)
    return JSONResponse(
        {
            "added": 0,
            "total": len(data),
            "opencode_default_model": settings_store.get_str(
                "opencode_default_model", "claude-opus-4-8"
            ),
            "opencode_small_model": settings_store.get_str("opencode_small_model", ""),
        }
    )
