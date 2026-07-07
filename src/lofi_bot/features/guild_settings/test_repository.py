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


async def test_update_panel_upserts_panel_target() -> None:
    pool = FakePool()
    repository = GuildSettingsRepository(pool)

    await repository.update_panel(123, 456, 789)

    query, args = pool.execute_calls[0]
    assert "INSERT INTO guild_settings" in query
    assert "ON CONFLICT (guild_id) DO UPDATE" in query
    assert "panel_channel_id = EXCLUDED.panel_channel_id" in query
    assert args == (123, 456, 789)


async def test_update_member_commands_enabled_upserts_setting() -> None:
    pool = FakePool()
    repository = GuildSettingsRepository(pool)

    await repository.update_member_commands_enabled(123, True)

    query, args = pool.execute_calls[0]
    assert "INSERT INTO guild_settings" in query
    assert "member_commands_enabled" in query
    assert "ON CONFLICT (guild_id) DO UPDATE" in query
    assert "member_commands_enabled = EXCLUDED.member_commands_enabled" in query
    assert args == (123, True)


async def test_update_voice_event_sounds_enabled_upserts_setting() -> None:
    pool = FakePool()
    repository = GuildSettingsRepository(pool)

    await repository.update_voice_event_sounds_enabled(123, True)

    query, args = pool.execute_calls[0]
    assert "INSERT INTO guild_settings" in query
    assert "voice_event_sounds_enabled" in query
    assert "ON CONFLICT (guild_id) DO UPDATE" in query
    assert "voice_event_sounds_enabled = EXCLUDED.voice_event_sounds_enabled" in query
    assert args == (123, True)
