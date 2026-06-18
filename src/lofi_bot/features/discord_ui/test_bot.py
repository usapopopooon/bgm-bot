from __future__ import annotations

from types import SimpleNamespace

from lofi_bot.features.discord_ui import bot as bot_module
from lofi_bot.features.discord_ui.bot import LofiDiscordBot
from lofi_bot.features.guild_settings.repository import GuildSettings


class FakeGuildSettingsRepository:
    def __init__(self, settings: list[GuildSettings]) -> None:
        self._settings = settings
        self.list_calls = 0
        self.panel_updates: list[tuple[int, int, int]] = []

    async def list_stay_connected(self) -> list[GuildSettings]:
        self.list_calls += 1
        return self._settings

    async def get_or_create(self, guild_id: int, default_category: str) -> GuildSettings:
        return GuildSettings(
            guild_id=guild_id,
            voice_channel_id=None,
            selected_category=default_category,
            volume=0.01,
            stay_connected=False,
            panel_channel_id=None,
            panel_message_id=None,
        )

    async def update_panel(self, guild_id: int, channel_id: int, message_id: int) -> None:
        self.panel_updates.append((guild_id, channel_id, message_id))


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

    def current_track(self, guild_id: int):
        return None

    def is_paused(self, guild_id: int) -> bool:
        return False


class FakeScheduler:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True


class FakeGuild:
    def __init__(self, guild_id: int, voice_client=None) -> None:  # noqa: ANN001
        self.id = guild_id
        self.voice_client = voice_client


class FakeVoiceChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


class FakeBotVoiceClient:
    def __init__(self, channel: FakeVoiceChannel, connected: bool = True) -> None:
        self.channel = channel
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


class FakeVoiceState:
    def __init__(self, channel: FakeVoiceChannel | None) -> None:
        self.channel = channel


class FakeVoiceMember:
    def __init__(self, guild: FakeGuild, bot: bool = False) -> None:
        self.guild = guild
        self.bot = bot


class FakePermissions:
    def __init__(self, administrator: bool) -> None:
        self.administrator = administrator


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.deferred = False

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self.messages.append((content, ephemeral))

    async def defer(self, thinking: bool = False) -> None:
        self.deferred = thinking


class FakeMessageChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


class FakeMessage:
    def __init__(self, channel_id: int, message_id: int) -> None:
        self.id = message_id
        self.channel = FakeMessageChannel(channel_id)


class FakeFollowup:
    def __init__(self, channel_id: int = 456, message_id: int = 789) -> None:
        self.channel_id = channel_id
        self.message_id = message_id
        self.messages: list[tuple[object, object, bool]] = []

    async def send(self, *, embed, view, wait: bool = False):  # noqa: ANN001, ANN201
        self.messages.append((embed, view, wait))
        return FakeMessage(self.channel_id, self.message_id)


class FakeInteraction:
    def __init__(self, guild_id: int | None, administrator: bool) -> None:
        self.guild = FakeGuild(guild_id) if guild_id is not None else None
        self.permissions = FakePermissions(administrator)
        self.response = FakeResponse()
        self.followup = FakeFollowup()


async def test_on_ready_presence_does_not_advertise_admin_command() -> None:
    scheduler = FakeScheduler()
    activities = []
    bot = object.__new__(LofiDiscordBot)
    bot.scheduler = scheduler
    bot._connection = SimpleNamespace(user="BGM Bot")
    bot._restored_stay_connected = True

    async def change_presence(*, activity):  # noqa: ANN001
        activities.append(activity)

    bot.change_presence = change_presence

    await LofiDiscordBot.on_ready(bot)

    assert scheduler.started is True
    assert isinstance(activities[0], bot_module.discord.CustomActivity)
    assert activities[0].name == "BGMを流しています"
    assert "/" not in activities[0].name


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


async def test_voice_state_update_ignores_unrelated_channel_changes() -> None:
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=FakeBotVoiceClient(bot_channel))
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild),
        FakeVoiceState(FakeVoiceChannel(111)),
        FakeVoiceState(FakeVoiceChannel(222)),
    )

    assert player_manager.leave_if_alone_calls == []


async def test_voice_state_update_checks_leave_when_member_leaves_bot_channel() -> None:
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=FakeBotVoiceClient(bot_channel))
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )

    assert player_manager.leave_if_alone_calls == [guild.id]


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


def test_panel_command_does_not_default_to_admin_permission() -> None:
    bot = object.__new__(LofiDiscordBot)
    command = bot_module.app_commands.Command(
        name="panel",
        description="操作パネルを再投稿します",
        callback=bot._panel_command,
    )

    assert command.default_permissions is None


async def test_panel_command_posts_panel_for_non_admin() -> None:
    guild_settings = FakeGuildSettingsRepository([])
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = FakePlayerManager()
    bot.settings = type("FakeSettings", (), {"default_category": "chill"})()
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._panel_command(bot, interaction)

    assert interaction.response.deferred is True
    assert len(interaction.followup.messages) == 1
    assert guild_settings.panel_updates == [(123, 456, 789)]


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
