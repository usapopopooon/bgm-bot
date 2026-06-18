from __future__ import annotations

from lofi_bot.features.guild_settings.repository import GuildSettingsRepository


class FakePool:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, query: str, *args: object) -> None:
        self.execute_calls.append((query, args))


async def test_clear_voice_channel_removes_saved_voice_channel() -> None:
    pool = FakePool()
    repository = GuildSettingsRepository(pool)

    await repository.clear_voice_channel(123)

    query, args = pool.execute_calls[0]
    assert "SET voice_channel_id = NULL" in query
    assert args == (123,)
