"""Private documentation site (mounted at ``/docs/``).

Serves the *built* VitePress usage docs as static files, but only to users who
can log into the platform — this is a privately-deployed docs site. Every
request must present a valid dashboard session; otherwise it is rejected with
``401`` (missing/invalid credential) or ``403`` (a disabled account).

Because the docs are opened as a full-page navigation (a new browser tab), the
SPA can't attach its ``Authorization`` header. Instead the dashboard links to
``/docs/?token=<session-jwt>``: on the first hit the token is validated, swapped
for an ``HttpOnly`` cookie, and the browser is redirected to the clean URL. Every
subsequent request (pages, assets, client-side navigations) authenticates via
that cookie — which supports VitePress's SPA-style routing and asset loading.

The served tree fully supports a VitePress build: directory ``index.html``,
clean-URL ``.html`` resolution, hashed ``/assets/`` with long-cache headers, and
the generated ``404.html`` as the not-found fallback.
"""

from __future__ import annotations

import mimetypes
from functools import lru_cache
from pathlib import Path

import jwt
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select

from voidswitch import __version__
from voidswitch.core.config import get_settings
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger
from voidswitch.core.security import decode_session_token
from voidswitch.models.db import User

log = get_logger("docs")

# HttpOnly cookie the docs site uses once the query-param token has been
# validated. Scoped to /docs so it never leaks to the API/gateway.
DOCS_COOKIE = "vs_docs_session"

subapp = FastAPI(
    title="VoidSwitch — Docs",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@lru_cache(maxsize=1)
def _docs_root() -> Path:
    """Resolve the built docs directory (``.vitepress/dist``).

    Prefers the configured ``server.docs_dir``; otherwise tries the in-image
    location baked by the Docker build, then the repo layout used in local dev.
    """
    configured = get_settings().server.docs_dir.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    candidates = (
        Path("/app/docs/dist"),
        Path(__file__).resolve().parents[3] / "docs" / ".vitepress" / "dist",
    )
    for cand in candidates:
        if cand.exists():
            return cand.resolve()
    # Nothing found yet — return the docker path; requests will 404 until built.
    return candidates[0]


async def _resolve_user(token: str | None) -> User | None:
    """Validate a session token the same way the dashboard API does, or None."""
    if not token:
        return None
    secret = get_settings().server.secret_key
    try:
        claims = decode_session_token(token, secret=secret)
    except jwt.PyJWTError:
        return None
    sub = str(claims.get("sub") or "")
    if not sub:
        return None
    async with get_database().session() as session:
        user = (
            await session.execute(select(User).where(User.sub == sub))
        ).scalar_one_or_none()
        if user is None:
            return None
        try:
            token_epoch = int(str(claims.get("epoch", 0) or 0))
        except (TypeError, ValueError):
            token_epoch = 0
        if token_epoch != (user.session_epoch or 0):
            return None
        return user


def _safe_target(rel: str) -> Path | None:
    """Map a request path to a file within the docs root (no traversal), or None."""
    root = _docs_root()
    rel = rel.lstrip("/")
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        return None
    return target


def _file_response(path: Path, *, status_code: int = 200) -> FileResponse:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers: dict[str, str] = {}
    # Hashed assets are immutable; the HTML entry must never be cached stale.
    if "/assets/" in path.as_posix():
        headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.suffix == ".html":
        headers["Cache-Control"] = "no-cache"
    return FileResponse(path, media_type=media_type, status_code=status_code, headers=headers)


@subapp.get("/{path:path}")
async def serve(path: str, request: Request) -> Response:
    """Authenticate, then serve a static docs file with SPA/clean-URL fallback."""
    # Auth: a `?token=` bridges to an HttpOnly cookie; otherwise use the cookie.
    query_token = request.query_params.get("token")
    if query_token:
        user = await _resolve_user(query_token)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session.")
        if not user.enabled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled.")
        # Redirect to the clean URL (drop the token from the address bar) and set
        # the cookie so subsequent asset/page requests authenticate seamlessly.
        redirect = RedirectResponse(url=request.url.path, status_code=status.HTTP_302_FOUND)
        redirect.set_cookie(
            DOCS_COOKIE,
            query_token,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=get_settings().server.session_ttl_minutes * 60,
            path="/docs",
        )
        return redirect

    user = await _resolve_user(request.cookies.get(DOCS_COOKIE))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to view the documentation.")
    if not user.enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled.")

    root = _docs_root()
    if not root.exists():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Documentation has not been built yet.",
        )

    target = _safe_target(path)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")

    # Directory → its index.html.
    if target.is_dir():
        index = target / "index.html"
        if index.is_file():
            return _file_response(index)
    # Exact file hit.
    if target.is_file():
        return _file_response(target)
    # Clean URL: /guide/foo → /guide/foo.html.
    if path:
        html = _safe_target(path.rstrip("/") + ".html")
        if html is not None and html.is_file():
            return _file_response(html)
    # Fallback: VitePress's generated 404 page (served with a 404 status).
    not_found = root / "404.html"
    if not_found.is_file():
        return _file_response(not_found, status_code=status.HTTP_404_NOT_FOUND)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
