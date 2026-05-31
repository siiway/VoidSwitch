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
from voidswitch.models.db import ApiKey, Provider, Proxy, User, VoidToken
from voidswitch.services import settings_store
from voidswitch.services.network import get_pool


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
        result = {
            "user_id": user.id,
            "user_sub": user.sub,
            "token": plaintext_token,
            "token_id": token.id,
            "provider_id": provider.id,
            "key_id": key.id,
        }
    return result


@pytest_asyncio.fixture
async def client(db: Database) -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def add_proxy(db: Database, url: str) -> int:
    async with db.session() as session:
        proxy = Proxy(url=url, status="active")
        session.add(proxy)
        await session.flush()
        return proxy.id


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
