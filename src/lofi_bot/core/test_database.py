from __future__ import annotations

import pytest

from lofi_bot.core import database as database_module
from lofi_bot.core.database import Database


@pytest.mark.asyncio
async def test_connect_retries_until_database_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = object()
    calls: list[int] = []
    sleeps: list[float] = []

    async def fake_create_pool(url: str, *, min_size: int, max_size: int) -> object:
        calls.append(max_size)
        if len(calls) == 1:
            raise OSError("database is starting")
        return pool

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(database_module.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr(database_module.asyncio, "sleep", fake_sleep)

    database = Database("postgresql://lofi:password@db:5432/lofi")
    await database.connect(attempts=2, delay_seconds=0.5)

    assert database.pool is pool
    assert calls == [5, 5]
    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_connect_raises_after_retry_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_create_pool(url: str, *, min_size: int, max_size: int) -> object:
        raise OSError("database is still unavailable")

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(database_module.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr(database_module.asyncio, "sleep", fake_sleep)

    database = Database("postgresql://lofi:password@db:5432/lofi")

    with pytest.raises(RuntimeError, match="Database did not become ready"):
        await database.connect(attempts=3, delay_seconds=0.5)

    assert sleeps == [0.5, 0.5]
