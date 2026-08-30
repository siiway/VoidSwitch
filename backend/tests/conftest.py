"""Shared test fixtures."""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from voidswitch.constants import KeyStatus
from voidswitch.core.config import get_settings
from voidswitch.core.database import Database, init_database
from voidswitch.core.security import (
    encrypt_secret,
    generate_void_token,
    hash_token,
    token_fingerprint,
)
from voidswitch.main import create_app
from voidswitch.models.db import (
    ApiKey,
    ExposedModel,
    Node,
    Provider,
    Route,
    RouteLayer,
    RoutePoolEntry,
    User,
    VoidToken,
)
from voidswitch.services import routing, settings_store
from voidswitch.services.network import get_pool


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """The rate limiters are process-wide singletons, but every test gets a fresh
    database whose user/token ids restart at 1. Without a reset, hits from an
    earlier test keep counting against the reused ids in later tests — spurious
    429s once the always-on operation limit (30/20s) accumulates enough."""
    from voidswitch.core import ratelimit

    ratelimit.operation_limiter.clear()
    ratelimit.call_limiter.clear()
    ratelimit.gateway_rpm_limiter.clear()
    yield


@pytest.fixture
def settings():
    return get_settings()


@pytest_asyncio.fixture
async def db(tmp_path) -> AsyncIterator[Database]:
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    database = init_database(url)
    await database.create_all()
    async with database.session() as session:
        await settings_store.ensure_defaults(session)
        await settings_store.load_all(session)
        await routing.ensure_seeded_groups(session)
    try:
        yield database
    finally:
        await get_pool().aclose()
        await database.dispose()


@pytest_asyncio.fixture
async def seeded(db: Database):
    """Seed an owner user, a token, a DeepSeek provider with one active key."""
    secret_key = get_settings().server.secret_key
    plaintext_token = generate_void_token()
    async with db.session() as session:
        user = User(sub="user-1", username="alice", email="a@example.com", role="owner")
        session.add(user)
        await session.flush()
        token = VoidToken(
            user_id=user.id,
            name="default",
            token_hash=hash_token(plaintext_token),
            token_prefix=token_fingerprint(plaintext_token),
        )
        session.add(token)
        provider = Provider(
            name="deepseek",
            slug="deepseek",
            type="deepseek",
            base_url="https://api.deepseek.com",
            models=["deepseek-chat", "*"],
            priority=10,
        )
        session.add(provider)
        await session.flush()
        key = ApiKey(
            provider_id=provider.id,
            key_ciphertext=encrypt_secret("sk-test-1", secret=secret_key),
            key_hash=hash_token("sk-test-1"),
            key_preview="sk-t…st-1",
            status=KeyStatus.ACTIVE.value,
        )
        session.add(key)
        await session.flush()
        # Expose the served model so the gateway can dispatch to it.
        exposed = ExposedModel(model_id="deepseek-chat")
        session.add(exposed)
        await session.flush()
        # Build the route directly (avoiding get_or_create_route's lazy-load of
        # ``exposed.route`` on a freshly-flushed object, which trips MissingGreenlet).
        route = Route(exposed_model_id=exposed.id)
        session.add(route)
        await session.flush()
        layer = RouteLayer(route_id=route.id, position=0, max_attempts=1)
        session.add(layer)
        await session.flush()
        session.add(
            RoutePoolEntry(
                layer_id=layer.id,
                provider_id=provider.id,
                upstream_model="deepseek-chat",
            )
        )
        await session.flush()
        result = {
            "user_id": user.id,
            "user_sub": user.sub,
            "token": plaintext_token,
            "token_id": token.id,
            "provider_id": provider.id,
            "key_id": key.id,
            "exposed_model_id": exposed.id,
            "exposed_model": "deepseek-chat",
        }
    return result


@pytest_asyncio.fixture
async def client(db: Database) -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def add_node(db: Database, url: str) -> int:
    async with db.session() as session:
        node = Node(url=url, type="http", status="active")
        session.add(node)
        await session.flush()
        default = await routing.default_group(session)
        if default is not None:
            from voidswitch.models.db import NodeGroupMember

            session.add(NodeGroupMember(group_id=default.id, node_id=node.id))
        await session.flush()
        return node.id


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
