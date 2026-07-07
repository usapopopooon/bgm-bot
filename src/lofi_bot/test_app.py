from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest

from lofi_bot import app


class FakeBot:
    def __init__(self) -> None:
        self.closed = asyncio.Event()
        self.close_calls = 0
        self.shutdown_started = False

    def begin_shutdown(self) -> None:
        self.shutdown_started = True

    async def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


async def test_wait_for_bot_or_shutdown_returns_when_shutdown_is_requested() -> None:
    shutdown_event = asyncio.Event()
    started = asyncio.Event()

    async def run_forever() -> None:
        started.set()
        await asyncio.Event().wait()

    bot_task = asyncio.create_task(run_forever())
    await started.wait()

    shutdown_event.set()
    await app._wait_for_bot_or_shutdown(bot_task, shutdown_event)

    assert not bot_task.done()
    bot_task.cancel()
    with suppress(asyncio.CancelledError):
        await bot_task


async def test_wait_for_bot_or_shutdown_propagates_bot_task_errors() -> None:
    shutdown_event = asyncio.Event()

    async def fail() -> None:
        raise RuntimeError("discord failed")

    bot_task = asyncio.create_task(fail())

    with pytest.raises(RuntimeError, match="discord failed"):
        await app._wait_for_bot_or_shutdown(bot_task, shutdown_event)


async def test_close_discord_bot_closes_client_and_waits_for_task() -> None:
    bot = FakeBot()

    async def run_until_closed() -> None:
        await bot.closed.wait()

    bot_task = asyncio.create_task(run_until_closed())

    await app._close_discord_bot(bot, bot_task)

    assert bot.close_calls == 1
    assert bot_task.done()


async def test_close_discord_bot_cancels_stubborn_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "BOT_CLOSE_TIMEOUT_SECONDS", 0.01)
    bot = FakeBot()

    async def run_forever() -> None:
        await asyncio.Event().wait()

    bot_task = asyncio.create_task(run_forever())

    await app._close_discord_bot(bot, bot_task)

    assert bot.close_calls == 1
    assert bot_task.cancelled()


async def test_shutdown_runtime_attempts_all_steps_when_one_fails() -> None:
    calls: list[str] = []
    bot = FakeBot()

    class FakeScheduler:
        async def stop(self) -> None:
            calls.append("scheduler")
            raise RuntimeError("scheduler failed")

    class FakePlayerManager:
        async def close_all(self) -> None:
            calls.append("players")

    class FakeJoinAnnouncements:
        async def close(self) -> None:
            calls.append("announcements")

    async def run_until_closed() -> None:
        await bot.closed.wait()
        calls.append("bot")

    bot_task = asyncio.create_task(run_until_closed())

    await app._shutdown_runtime(
        FakeScheduler(),
        FakePlayerManager(),
        FakeJoinAnnouncements(),
        bot,
        bot_task,
    )

    assert bot.shutdown_started is True
    assert calls == ["scheduler", "announcements", "players", "bot"]
