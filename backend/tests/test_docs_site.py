"""Private docs site: auth gating + static serving with token→cookie bridge."""

from __future__ import annotations

from pathlib import Path

import pytest
from voidswitch.api import docs_site
from voidswitch.core.config import get_settings
from voidswitch.core.security import create_session_token
from voidswitch.models.db import User

pytestmark = pytest.mark.asyncio

_DIST = Path(__file__).resolve().parents[2] / "docs" / ".vitepress" / "dist"
_needs_build = pytest.mark.skipif(
    not (_DIST / "index.html").is_file(),
    reason="docs not built (run `bun run docs:build` in docs/)",
)


def _token(sub: str) -> str:
    return create_session_token(
        secret=get_settings().server.secret_key,
        subject=sub,
        extra={"role": "member", "name": "mia", "epoch": 0},
    )


async def _seed(db) -> None:
    async with db.session() as session:
        session.add(User(sub="docs-user", username="mia", role="member"))
        await session.flush()


async def test_docs_requires_auth(client, db):
    docs_site._docs_root.cache_clear()
    resp = await client.get("/docs/")
    assert resp.status_code == 401


@_needs_build
async def test_docs_token_bridges_to_cookie_then_serves(client, db):
    docs_site._docs_root.cache_clear()
    await _seed(db)
    token = _token("docs-user")

    # Token in the query → redirect that sets the cookie (no auto-follow).
    bridged = await client.get(f"/docs/?token={token}", follow_redirects=False)
    assert bridged.status_code == 302
    assert docs_site.DOCS_COOKIE in bridged.headers.get("set-cookie", "")

    # With the cookie, the index page is served.
    client.cookies.set(docs_site.DOCS_COOKIE, token)
    page = await client.get("/docs/")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
