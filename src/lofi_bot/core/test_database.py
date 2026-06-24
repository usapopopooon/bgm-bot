from __future__ import annotations

import pytest

from lofi_bot.core import database as database_module
from lofi_bot.core.database import Database


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)


class FakeAcquire:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self._connection

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakePool:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.connection)


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


@pytest.mark.asyncio
async def test_migrate_sets_default_volume_to_one_percent() -> None:
    pool = FakePool()
    database = Database("postgresql://lofi:password@db:5432/lofi")
    database.pool = pool

    await database.migrate()

    statement = pool.connection.statements[0]
    assert "volume REAL NOT NULL DEFAULT 0.01" in statement
    assert "ALTER COLUMN volume SET DEFAULT 0.01" in statement
    assert "instrumental_only BOOLEAN NOT NULL DEFAULT FALSE" in statement
    assert "ADD COLUMN IF NOT EXISTS instrumental_only" in statement
    assert "stay_connected BOOLEAN NOT NULL DEFAULT FALSE" in statement
    assert "ADD COLUMN IF NOT EXISTS stay_connected" in statement
    assert "member_commands_enabled BOOLEAN NOT NULL DEFAULT FALSE" in statement
    assert "ADD COLUMN IF NOT EXISTS member_commands_enabled" in statement
    assert "selected_category TEXT NOT NULL DEFAULT 'chill'" in statement
    assert "SET selected_category = 'chill'" in statement
    assert "idx_play_history_guild_category_track_played" in statement
