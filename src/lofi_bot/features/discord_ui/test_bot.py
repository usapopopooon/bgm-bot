from __future__ import annotations

from lofi_bot.features.discord_ui import bot as bot_module
from lofi_bot.features.discord_ui.bot import LofiDiscordBot
from lofi_bot.features.guild_settings.repository import GuildSettings


class FakeGuildSettingsRepository:
    def __init__(self, settings: list[GuildSettings]) -> None:
        self._settings = settings
        self.list_calls = 0

    async def list_stay_connected(self) -> list[GuildSettings]:
        self.list_calls += 1
        return self._settings


class FakePlayerManager:
    def __init__(self) -> None:
        self.connected: list[tuple[int, int]] = []
        self.started: list[int] = []

    async def connect(self, guild, channel):  # noqa: ANN001, ANN201
        self.connected.append((guild.id, channel.id))

    async def start_saved_category(self, guild):  # noqa: ANN001
        self.started.append(guild.id)


class FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id


class FakeVoiceChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


async def test_restore_stay_connected_voice_reconnects_saved_channels(monkeypatch) -> None:
    guild = FakeGuild(123)
    channel = FakeVoiceChannel(456)
    settings = GuildSettings(
        guild_id=guild.id,
        voice_channel_id=channel.id,
        selected_category="chill",
        volume=0.01,
        stay_connected=True,
        panel_channel_id=None,
        panel_message_id=None,
    )
    guild_settings = FakeGuildSettingsRepository([settings])
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.get_guild = lambda guild_id: guild if guild_id == guild.id else None
    bot.get_channel = lambda channel_id: channel if channel_id == channel.id else None

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module.discord, "VoiceChannel", FakeVoiceChannel)

    await LofiDiscordBot._restore_stay_connected_voice(bot)

    assert guild_settings.list_calls == 1
    assert player_manager.connected == [(guild.id, channel.id)]
    assert player_manager.started == [guild.id]
    assert refreshed == [guild.id]


async def test_restore_stay_connected_voice_skips_missing_guild(monkeypatch) -> None:
    channel = FakeVoiceChannel(456)
    settings = GuildSettings(
        guild_id=123,
        voice_channel_id=channel.id,
        selected_category="chill",
        volume=0.01,
        stay_connected=True,
        panel_channel_id=None,
        panel_message_id=None,
    )
    guild_settings = FakeGuildSettingsRepository([settings])
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.get_guild = lambda guild_id: None
    bot.get_channel = lambda channel_id: channel
    monkeypatch.setattr(bot_module.discord, "VoiceChannel", FakeVoiceChannel)

    await LofiDiscordBot._restore_stay_connected_voice(bot)

    assert player_manager.connected == []
    assert player_manager.started == []
