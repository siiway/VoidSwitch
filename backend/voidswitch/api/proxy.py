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

from voidswitch.constants import ApiStyle
from voidswitch.core import auth
from voidswitch.core.database import get_session
from voidswitch.core.logging import get_logger, redact_headers
from voidswitch.core.security import hash_token
from voidswitch.models.db import Provider, VoidToken
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
    authed = await auth.authenticate_void_token(request, session, authorization, x_api_key)
    payload = await _body(request)

    model = payload.get("model")
    if not isinstance(model, str) or not model:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing 'model'.")

    _check_model_allowed(authed.token, model)
    _check_rpm(authed.token)

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
        passthrough_headers=passthrough,
    )
    result = await dispatch(req)

    if result.is_stream and result.stream is not None:
        return StreamingResponse(
            result.stream,
            status_code=result.status_code,
            media_type=result.media_type,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return Response(
        content=result.content or b"{}",
        status_code=result.status_code,
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
    # Authenticate, tolerating either credential header.
    raw = (authorization or "").removeprefix("Bearer ").strip() or x_api_key
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key.")
    token = (
        await session.execute(select(VoidToken).where(VoidToken.token_hash == hash_token(raw)))
    ).scalar_one_or_none()
    if token is None or not token.enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key.")

    providers = (
        (await session.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
    )
    seen: set[str] = set()
    data: list[dict[str, object]] = []
    allowed = token.allowed_models or []
    for provider in providers:
        for model in provider.models or []:
            if model == "*" or model in seen:
                continue
            if allowed and not any(p == "*" or p == model or fnmatch(model, p) for p in allowed):
                continue
            seen.add(model)
            data.append(
                {
                    "id": model,
                    "object": "model",
                    "created": 0,
                    "owned_by": provider.name,
                }
            )
    return JSONResponse({"object": "list", "data": data})
