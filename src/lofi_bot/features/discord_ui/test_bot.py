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
        self.is_playing = True
        self.volumes: list[tuple[int, float]] = []
        self.stay_connected: list[tuple[int, bool]] = []
        self.leave_if_alone_calls: list[int] = []
        self.left_alone = False
        self.leave_calls: list[tuple[int, bool, bool]] = []
        self.left = True

    async def connect(self, guild, channel):  # noqa: ANN001, ANN201
        self.connected.append((guild.id, channel.id))

    async def start_saved_category(self, guild):  # noqa: ANN001
        self.started.append(guild.id)

    async def set_volume(self, guild_id: int, volume: float) -> bool:
        self.volumes.append((guild_id, volume))
        return self.is_playing

    async def set_stay_connected(self, guild_id: int, stay_connected: bool) -> None:
        self.stay_connected.append((guild_id, stay_connected))

    async def leave_if_alone(self, guild) -> bool:  # noqa: ANN001
        self.leave_if_alone_calls.append(guild.id)
        return self.left_alone

    async def leave(
        self,
        guild_id: int,
        *,
        clear_saved_channel: bool = False,
        disable_stay_connected: bool = False,
    ) -> bool:
        self.leave_calls.append((guild_id, clear_saved_channel, disable_stay_connected))
        return self.left


class FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id


class FakeVoiceChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


class FakePermissions:
    def __init__(self, administrator: bool) -> None:
        self.administrator = administrator


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self.messages.append((content, ephemeral))


class FakeInteraction:
    def __init__(self, guild_id: int | None, administrator: bool) -> None:
        self.guild = FakeGuild(guild_id) if guild_id is not None else None
        self.permissions = FakePermissions(administrator)
        self.response = FakeResponse()


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


def test_admin_commands_default_to_admin_permission() -> None:
    bot = object.__new__(LofiDiscordBot)
    commands = [
        bot_module.app_commands.Command(
            name="vc",
            description="VCに接続して操作パネルを表示します",
            callback=bot._vc_command,
        ),
        bot_module.app_commands.Command(
            name="volume",
            description="音量を変更します（管理者のみ）",
            callback=bot._volume_command,
        ),
        bot_module.app_commands.Command(
            name="stay",
            description="Stayを切り替えます（管理者のみ）",
            callback=bot._stay_command,
        ),
        bot_module.app_commands.Command(
            name="leave",
            description="VCから退出します（管理者のみ）",
            callback=bot._leave_command,
        ),
    ]

    assert all(command.default_permissions is not None for command in commands)
    assert all(command.default_permissions.administrator for command in commands)


async def test_volume_command_rejects_non_admin() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    refreshed: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._volume_command(bot, interaction, 50)

    assert player_manager.volumes == []
    assert refreshed == []
    assert interaction.response.messages == [
        ("音量を変更できるのは管理者だけです。", True),
    ]


async def test_volume_command_sets_volume_for_admin() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    refreshed: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=True)

    await LofiDiscordBot._volume_command(bot, interaction, 42)

    assert player_manager.volumes == [(123, 0.42)]
    assert refreshed == [123]
    assert interaction.response.messages == [
        ("音量を 42% にしました。", True),
    ]


async def test_stay_command_rejects_non_admin() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot._refresh_panel_message = _noop_refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._stay_command(bot, interaction, True)

    assert player_manager.stay_connected == []
    assert player_manager.leave_if_alone_calls == []
    assert interaction.response.messages == [
        ("Stayを変更できるのは管理者だけです。", True),
    ]


async def test_stay_command_sets_enabled_for_admin() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    refreshed: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=True)

    await LofiDiscordBot._stay_command(bot, interaction, True)

    assert player_manager.stay_connected == [(123, True)]
    assert player_manager.leave_if_alone_calls == []
    assert refreshed == [123]
    assert interaction.response.messages == [
        ("Stayを ON にしました。", True),
    ]


async def test_stay_command_turns_off_and_leaves_if_alone_for_admin() -> None:
    player_manager = FakePlayerManager()
    player_manager.left_alone = True
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot._refresh_panel_message = _noop_refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=True)

    await LofiDiscordBot._stay_command(bot, interaction, False)

    assert player_manager.stay_connected == [(123, False)]
    assert player_manager.leave_if_alone_calls == [123]
    assert interaction.response.messages == [
        ("Stayを OFF にしました。 VCが空だったため退出しました。", True),
    ]


async def test_leave_command_rejects_non_admin() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot._refresh_panel_message = _noop_refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._leave_command(bot, interaction)

    assert player_manager.leave_calls == []
    assert interaction.response.messages == [
        ("VCから退出できるのは管理者だけです。", True),
    ]


async def test_leave_command_leaves_for_admin() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    refreshed: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=True)

    await LofiDiscordBot._leave_command(bot, interaction)

    assert player_manager.leave_calls == [(123, True, True)]
    assert refreshed == [123]
    assert interaction.response.messages == [
        ("VCから退出しました。", True),
    ]


async def _noop_refresh_panel(guild_id: int) -> None:
    pass
