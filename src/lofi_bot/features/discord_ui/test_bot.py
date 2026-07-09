from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from lofi_bot.features.discord_ui import bot as bot_module
from lofi_bot.features.discord_ui.bot import LofiDiscordBot
from lofi_bot.features.guild_settings.repository import GuildSettings


class FakeGuildSettingsRepository:
    def __init__(self, settings: list[GuildSettings]) -> None:
        self._settings = settings
        self.list_calls = 0
        self.panel_updates: list[tuple[int, int, int]] = []
        self.member_command_updates: list[tuple[int, bool]] = []
        self.voice_event_sound_updates: list[tuple[int, bool]] = []

    async def list_stay_connected(self) -> list[GuildSettings]:
        self.list_calls += 1
        return self._settings

    async def get_or_create(self, guild_id: int, default_category: str) -> GuildSettings:
        for settings in self._settings:
            if settings.guild_id == guild_id:
                return settings
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

    async def update_member_commands_enabled(
        self,
        guild_id: int,
        member_commands_enabled: bool,
    ) -> None:
        self.member_command_updates.append((guild_id, member_commands_enabled))
        for index, settings in enumerate(self._settings):
            if settings.guild_id == guild_id:
                self._settings[index] = replace(
                    settings,
                    member_commands_enabled=member_commands_enabled,
                )
                return

        self._settings.append(
            GuildSettings(
                guild_id=guild_id,
                voice_channel_id=None,
                selected_category="chill",
                volume=0.01,
                stay_connected=False,
                panel_channel_id=None,
                panel_message_id=None,
                member_commands_enabled=member_commands_enabled,
            )
        )

    async def update_voice_event_sounds_enabled(
        self,
        guild_id: int,
        voice_event_sounds_enabled: bool,
    ) -> None:
        self.voice_event_sound_updates.append((guild_id, voice_event_sounds_enabled))
        for index, settings in enumerate(self._settings):
            if settings.guild_id == guild_id:
                self._settings[index] = replace(
                    settings,
                    voice_event_sounds_enabled=voice_event_sounds_enabled,
                )
                return

        self._settings.append(
            GuildSettings(
                guild_id=guild_id,
                voice_channel_id=None,
                selected_category="chill",
                volume=0.01,
                stay_connected=False,
                panel_channel_id=None,
                panel_message_id=None,
                voice_event_sounds_enabled=voice_event_sounds_enabled,
            )
        )


class FakePlayerManager:
    def __init__(self) -> None:
        self.connected: list[tuple[int, int]] = []
        self.started: list[int] = []
        self.restarted: list[int] = []
        self.is_playing = True
        self.volumes: list[tuple[int, float]] = []
        self.stay_connected: list[tuple[int, bool]] = []
        self.current_stay_connected = False
        self.leave_if_alone_calls: list[int] = []
        self.left_alone = False
        self.leave_calls: list[tuple[int, bool, bool]] = []
        self.left = True
        self.external_disconnect_calls: list[int] = []
        self.externally_disconnected = True
        self.announcements: list[tuple[int, bytes]] = []
        self.accepts_announcement = True

    def set_track_changed_callback(self, callback) -> None:  # noqa: ANN001
        self.track_changed_callback = callback

    async def connect(self, guild, channel):  # noqa: ANN001, ANN201
        self.connected.append((guild.id, channel.id))

    async def start_saved_category(self, guild):  # noqa: ANN001
        self.started.append(guild.id)

    async def restart_after_reconnect(self, guild):  # noqa: ANN001
        self.restarted.append(guild.id)

    async def set_volume(self, guild_id: int, volume: float) -> bool:
        self.volumes.append((guild_id, volume))
        return self.is_playing

    async def get_stay_connected(self, guild_id: int) -> bool:
        return self.current_stay_connected

    async def set_stay_connected(self, guild_id: int, stay_connected: bool) -> None:
        self.current_stay_connected = stay_connected
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

    async def handle_external_disconnect(self, guild_id: int) -> bool:
        self.external_disconnect_calls.append(guild_id)
        return self.externally_disconnected

    async def enqueue_announcement(self, guild_id: int, audio_data: bytes) -> bool:
        self.announcements.append((guild_id, audio_data))
        return True

    def can_accept_announcement(self, guild_id: int) -> bool:
        return self.accepts_announcement

    def current_track(self, guild_id: int):
        return None

    def is_paused(self, guild_id: int) -> bool:
        return False


class FakeScheduler:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True


class FakeJoinAnnouncements:
    def __init__(
        self,
        *,
        enabled: bool = True,
        audio_data: bytes | None = b"wav",
        error: Exception | None = None,
    ) -> None:
        self.is_enabled = enabled
        self.audio_data = audio_data
        self.error = error
        self.calls: list[str] = []

    async def synthesize_join(self, guild_id: int, display_name: str) -> bytes | None:
        self.calls.append(f"join:{guild_id}:{display_name}")
        if self.error is not None:
            raise self.error
        return self.audio_data

    async def synthesize_leave(self, guild_id: int, display_name: str) -> bytes | None:
        self.calls.append(f"leave:{guild_id}:{display_name}")
        if self.error is not None:
            raise self.error
        return self.audio_data


class FakeGuild:
    def __init__(
        self,
        guild_id: int,
        voice_client=None,  # noqa: ANN001
        audit_log_entries: list[object] | None = None,
        audit_log_error: BaseException | None = None,
    ) -> None:
        self.id = guild_id
        self.voice_client = voice_client
        self.audit_log_entries = audit_log_entries or []
        self.audit_log_error = audit_log_error

    def audit_logs(self, **kwargs: object):  # noqa: ANN201
        async def entries():
            if self.audit_log_error is not None:
                raise self.audit_log_error
            for entry in self.audit_log_entries:
                yield entry

        return entries()


class FakeVoiceChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


class FakeBotVoiceClient:
    def __init__(self, channel: FakeVoiceChannel, connected: bool = True) -> None:
        self.channel = channel
        self.connected = connected
        self.disconnect_calls: list[bool] = []

    def is_connected(self) -> bool:
        return self.connected

    async def disconnect(self, *, force: bool = False) -> None:
        self.disconnect_calls.append(force)
        self.connected = False


class FakeVoiceState:
    def __init__(self, channel: FakeVoiceChannel | None) -> None:
        self.channel = channel


class FakeVoiceMember:
    def __init__(
        self,
        guild: FakeGuild,
        bot: bool = False,
        member_id: int = 111,
    ) -> None:
        self.guild = guild
        self.bot = bot
        self.id = member_id
        self.display_name = "User"


class FakeMemberVoice:
    def __init__(self, channel: FakeVoiceChannel | None) -> None:
        self.channel = channel


class FakeCommandMember:
    def __init__(self, channel: FakeVoiceChannel | None = None) -> None:
        self.voice = FakeMemberVoice(channel) if channel is not None else None


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
    def __init__(
        self,
        guild_id: int | None,
        administrator: bool,
        *,
        user: object | None = None,
        voice_client=None,  # noqa: ANN001
    ) -> None:
        self.guild = (
            FakeGuild(guild_id, voice_client=voice_client) if guild_id is not None else None
        )
        self.user = user if user is not None else SimpleNamespace()
        self.permissions = FakePermissions(administrator)
        self.response = FakeResponse()
        self.followup = FakeFollowup()


def _fake_settings() -> object:
    return type("FakeSettings", (), {"default_category": "chill"})()


def _guild_settings(
    guild_id: int = 123,
    *,
    member_commands_enabled: bool = False,
    voice_event_sounds_enabled: bool = False,
) -> GuildSettings:
    return GuildSettings(
        guild_id=guild_id,
        voice_channel_id=None,
        selected_category="chill",
        volume=0.01,
        stay_connected=False,
        panel_channel_id=None,
        panel_message_id=None,
        member_commands_enabled=member_commands_enabled,
        voice_event_sounds_enabled=voice_event_sounds_enabled,
    )


def _set_member_command_access(
    bot: LofiDiscordBot,
    *,
    member_commands_enabled: bool = False,
) -> FakeGuildSettingsRepository:
    guild_settings = FakeGuildSettingsRepository(
        [_guild_settings(member_commands_enabled=member_commands_enabled)]
    )
    bot.guild_settings = guild_settings
    bot.settings = _fake_settings()
    return guild_settings


def _set_voice_event_sounds_access(
    bot: LofiDiscordBot,
    *,
    voice_event_sounds_enabled: bool = False,
) -> FakeGuildSettingsRepository:
    guild_settings = FakeGuildSettingsRepository(
        [_guild_settings(voice_event_sounds_enabled=voice_event_sounds_enabled)]
    )
    bot.guild_settings = guild_settings
    bot.settings = _fake_settings()
    return guild_settings


async def test_on_ready_presence_does_not_advertise_admin_command() -> None:
    scheduler = FakeScheduler()
    activities = []
    bot = object.__new__(LofiDiscordBot)
    bot.scheduler = scheduler
    bot._connection = SimpleNamespace(user="BGM Bot")
    bot._restored_stay_connected = False
    bot.guild_settings = FakeGuildSettingsRepository([])
    bot.player_manager = FakePlayerManager()

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

    restored = await LofiDiscordBot._restore_stay_connected_voice(bot)

    assert restored is True
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

    restored = await LofiDiscordBot._restore_stay_connected_voice(bot)

    assert restored is False
    assert player_manager.connected == []
    assert player_manager.started == []


async def test_restore_stay_connected_voice_with_retries_until_success(monkeypatch) -> None:
    attempts = 0
    bot = object.__new__(LofiDiscordBot)
    bot._shutting_down = False
    monkeypatch.setattr(bot_module, "STAY_CONNECTED_RECONNECT_BASE_DELAY_SECONDS", 0)

    async def restore(completed_guild_ids=None) -> bool:  # noqa: ANN001
        nonlocal attempts
        attempts += 1
        return attempts == 2

    bot._restore_stay_connected_voice = restore

    await LofiDiscordBot._restore_stay_connected_voice_with_retries(bot)

    assert attempts == 2


async def test_restore_stay_connected_voice_with_retries_skips_completed_guilds(
    monkeypatch,
) -> None:
    completed_snapshots: list[set[int]] = []
    bot = object.__new__(LofiDiscordBot)
    bot._shutting_down = False
    monkeypatch.setattr(bot_module, "STAY_CONNECTED_RECONNECT_BASE_DELAY_SECONDS", 0)

    async def restore(completed_guild_ids: set[int] | None = None) -> bool:
        assert completed_guild_ids is not None
        completed_snapshots.append(set(completed_guild_ids))
        if not completed_guild_ids:
            completed_guild_ids.add(123)
            return False
        return True

    bot._restore_stay_connected_voice = restore

    await LofiDiscordBot._restore_stay_connected_voice_with_retries(bot)

    assert completed_snapshots == [set(), {123}]


async def test_setup_hook_registers_commands_without_panel() -> None:
    settings = type(
        "FakeSettings",
        (),
        {"default_category": "chill", "sync_commands": False, "discord_guild_id": None},
    )()
    bot = LofiDiscordBot(
        settings=settings,
        guild_settings=FakeGuildSettingsRepository([]),
        player_manager=FakePlayerManager(),
        scheduler=FakeScheduler(),
    )

    try:
        await bot.setup_hook()

        command_names = [command.name for command in bot.tree.get_commands()]
        assert command_names == [
            "play",
            "volume",
            "stay",
            "leave",
            "member_commands",
            "voice_event_sounds",
        ]
    finally:
        await bot.close()


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


async def test_voice_state_update_announces_member_joining_bot_channel() -> None:
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=FakeBotVoiceClient(bot_channel))
    player_manager = FakePlayerManager()
    join_announcements = FakeJoinAnnouncements(audio_data=b"announcement-wav")
    member = FakeVoiceMember(guild, member_id=789)
    member.display_name = "Alice"
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot.join_announcements = join_announcements
    _set_voice_event_sounds_access(bot, voice_event_sounds_enabled=True)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        member,
        FakeVoiceState(None),
        FakeVoiceState(bot_channel),
    )

    assert join_announcements.calls == ["join:123:Alice"]
    assert player_manager.announcements == [(guild.id, b"announcement-wav")]
    assert player_manager.leave_if_alone_calls == []


async def test_voice_state_update_announces_member_leaving_bot_channel() -> None:
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=FakeBotVoiceClient(bot_channel))
    player_manager = FakePlayerManager()
    join_announcements = FakeJoinAnnouncements(audio_data=b"leave-announcement-wav")
    member = FakeVoiceMember(guild, member_id=789)
    member.display_name = "Alice"
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot.join_announcements = join_announcements
    _set_voice_event_sounds_access(bot, voice_event_sounds_enabled=True)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        member,
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )

    assert join_announcements.calls == ["leave:123:Alice"]
    assert player_manager.announcements == [(guild.id, b"leave-announcement-wav")]
    assert player_manager.leave_if_alone_calls == [guild.id]


async def test_voice_state_update_skips_join_announcement_by_default() -> None:
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=FakeBotVoiceClient(bot_channel))
    player_manager = FakePlayerManager()
    join_announcements = FakeJoinAnnouncements(audio_data=b"announcement-wav")
    member = FakeVoiceMember(guild, member_id=789)
    member.display_name = "Alice"
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot.join_announcements = join_announcements
    _set_voice_event_sounds_access(bot)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        member,
        FakeVoiceState(None),
        FakeVoiceState(bot_channel),
    )

    assert join_announcements.calls == []
    assert player_manager.announcements == []


async def test_voice_state_update_logs_join_announcement_tts_error(
    caplog,
) -> None:
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=FakeBotVoiceClient(bot_channel))
    player_manager = FakePlayerManager()
    join_announcements = FakeJoinAnnouncements(error=RuntimeError("tts failed"))
    member = FakeVoiceMember(guild, member_id=789)
    member.display_name = "Alice"
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot.join_announcements = join_announcements
    _set_voice_event_sounds_access(bot, voice_event_sounds_enabled=True)
    caplog.set_level(logging.ERROR, logger=bot_module.LOGGER.name)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        member,
        FakeVoiceState(None),
        FakeVoiceState(bot_channel),
    )

    assert join_announcements.calls == ["join:123:Alice"]
    assert player_manager.announcements == []
    assert "Join announcement TTS failed unexpectedly guild=123 member=789" in caplog.messages


async def test_voice_state_update_skips_join_announcement_when_disabled() -> None:
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=FakeBotVoiceClient(bot_channel))
    player_manager = FakePlayerManager()
    join_announcements = FakeJoinAnnouncements(enabled=False)
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot.join_announcements = join_announcements

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild),
        FakeVoiceState(None),
        FakeVoiceState(bot_channel),
    )

    assert join_announcements.calls == []
    assert player_manager.announcements == []


async def test_voice_state_update_skips_join_announcement_when_player_queue_full() -> None:
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=FakeBotVoiceClient(bot_channel))
    player_manager = FakePlayerManager()
    player_manager.accepts_announcement = False
    join_announcements = FakeJoinAnnouncements()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot.join_announcements = join_announcements

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild),
        FakeVoiceState(None),
        FakeVoiceState(bot_channel),
    )

    assert join_announcements.calls == []
    assert player_manager.announcements == []


async def test_voice_state_update_treats_self_disconnect_like_manual_leave(monkeypatch) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=None)
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.external_disconnect_calls == [guild.id]
    assert player_manager.leave_if_alone_calls == []
    assert refreshed == [guild.id]


async def test_voice_state_update_restores_stay_connected_after_voice_reconnect_fails(
    monkeypatch,
) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=None)
    guild_settings = FakeGuildSettingsRepository(
        [
            GuildSettings(
                guild_id=guild.id,
                voice_channel_id=bot_channel.id,
                selected_category="chill",
                volume=0.01,
                stay_connected=True,
                panel_channel_id=None,
                panel_message_id=None,
            )
        ]
    )
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.settings = type("FakeSettings", (), {"default_category": "chill"})()
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    bot._last_gateway_recoverable_disconnect_at = bot_module.time.monotonic()
    bot.get_channel = lambda channel_id: bot_channel if channel_id == bot_channel.id else None

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module.discord, "VoiceChannel", FakeVoiceChannel)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.external_disconnect_calls == []
    assert player_manager.connected == [(guild.id, bot_channel.id)]
    assert player_manager.restarted == [guild.id]
    assert refreshed == [guild.id]


async def test_stay_connected_self_disconnect_is_manual_with_recent_audit_log(
    monkeypatch,
) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    recent_disconnect = SimpleNamespace(
        created_at=bot_module.datetime.now(bot_module.UTC),
        extra=SimpleNamespace(count=1),
    )
    guild = FakeGuild(123, voice_client=None, audit_log_entries=[recent_disconnect])
    guild_settings = FakeGuildSettingsRepository(
        [
            GuildSettings(
                guild_id=guild.id,
                voice_channel_id=bot_channel.id,
                selected_category="chill",
                volume=0.01,
                stay_connected=True,
                panel_channel_id=None,
                panel_message_id=None,
            )
        ]
    )
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.settings = type("FakeSettings", (), {"default_category": "chill"})()
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    bot._last_gateway_recoverable_disconnect_at = None

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.connected == []
    assert player_manager.started == []
    assert player_manager.external_disconnect_calls == [guild.id]
    assert refreshed == [guild.id]


async def test_stay_connected_self_disconnect_recovers_without_user_intent(
    monkeypatch,
) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    old_disconnect = SimpleNamespace(
        created_at=(
            bot_module.datetime.now(bot_module.UTC)
            - timedelta(seconds=bot_module.MANUAL_VOICE_DISCONNECT_AUDIT_WINDOW_SECONDS + 1)
        ),
        extra=SimpleNamespace(count=1),
    )
    guild = FakeGuild(123, voice_client=None, audit_log_entries=[old_disconnect])
    guild_settings = FakeGuildSettingsRepository(
        [
            GuildSettings(
                guild_id=guild.id,
                voice_channel_id=bot_channel.id,
                selected_category="chill",
                volume=0.01,
                stay_connected=True,
                panel_channel_id=None,
                panel_message_id=None,
            )
        ]
    )
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.settings = type("FakeSettings", (), {"default_category": "chill"})()
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    bot._last_gateway_recoverable_disconnect_at = None
    bot.get_channel = lambda channel_id: bot_channel if channel_id == bot_channel.id else None

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module.discord, "VoiceChannel", FakeVoiceChannel)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.external_disconnect_calls == []
    assert player_manager.connected == [(guild.id, bot_channel.id)]
    assert player_manager.restarted == [guild.id]
    assert refreshed == [guild.id]


async def test_stay_connected_self_disconnect_recovers_when_audit_log_unavailable(
    monkeypatch,
) -> None:
    class FakeForbidden(Exception):
        pass

    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=None, audit_log_error=FakeForbidden())
    guild_settings = FakeGuildSettingsRepository(
        [
            GuildSettings(
                guild_id=guild.id,
                voice_channel_id=bot_channel.id,
                selected_category="chill",
                volume=0.01,
                stay_connected=True,
                panel_channel_id=None,
                panel_message_id=None,
            )
        ]
    )
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.settings = type("FakeSettings", (), {"default_category": "chill"})()
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    bot._last_gateway_recoverable_disconnect_at = None
    bot.get_channel = lambda channel_id: bot_channel if channel_id == bot_channel.id else None

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module.discord, "Forbidden", FakeForbidden)
    monkeypatch.setattr(bot_module.discord, "VoiceChannel", FakeVoiceChannel)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.external_disconnect_calls == []
    assert player_manager.connected == [(guild.id, bot_channel.id)]
    assert player_manager.restarted == [guild.id]
    assert refreshed == [guild.id]


async def test_stay_connected_self_disconnect_ignores_ambiguous_audit_log(
    monkeypatch,
) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    recent_multi_disconnect = SimpleNamespace(
        created_at=bot_module.datetime.now(bot_module.UTC),
        extra=SimpleNamespace(count=2),
    )
    guild = FakeGuild(
        123,
        voice_client=None,
        audit_log_entries=[recent_multi_disconnect],
    )
    guild_settings = FakeGuildSettingsRepository(
        [
            GuildSettings(
                guild_id=guild.id,
                voice_channel_id=bot_channel.id,
                selected_category="chill",
                volume=0.01,
                stay_connected=True,
                panel_channel_id=None,
                panel_message_id=None,
            )
        ]
    )
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.settings = type("FakeSettings", (), {"default_category": "chill"})()
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    bot._last_gateway_recoverable_disconnect_at = None
    bot.get_channel = lambda channel_id: bot_channel if channel_id == bot_channel.id else None

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module.discord, "VoiceChannel", FakeVoiceChannel)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.external_disconnect_calls == []
    assert player_manager.connected == [(guild.id, bot_channel.id)]
    assert player_manager.restarted == [guild.id]
    assert refreshed == [guild.id]


async def test_gateway_recoverable_signal_overrides_ambiguous_audit_log(
    monkeypatch,
) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    recent_disconnect = SimpleNamespace(
        created_at=bot_module.datetime.now(bot_module.UTC),
        extra=SimpleNamespace(count=1),
    )
    guild = FakeGuild(123, voice_client=None, audit_log_entries=[recent_disconnect])
    guild_settings = FakeGuildSettingsRepository(
        [
            GuildSettings(
                guild_id=guild.id,
                voice_channel_id=bot_channel.id,
                selected_category="chill",
                volume=0.01,
                stay_connected=True,
                panel_channel_id=None,
                panel_message_id=None,
            )
        ]
    )
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.settings = type("FakeSettings", (), {"default_category": "chill"})()
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    bot._last_gateway_recoverable_disconnect_at = bot_module.time.monotonic()
    bot.get_channel = lambda channel_id: bot_channel if channel_id == bot_channel.id else None

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module.discord, "VoiceChannel", FakeVoiceChannel)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.external_disconnect_calls == []
    assert player_manager.connected == [(guild.id, bot_channel.id)]
    assert player_manager.restarted == [guild.id]
    assert refreshed == [guild.id]


async def test_user_requested_disconnect_overrides_gateway_recoverable_signal(
    monkeypatch,
) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=None)
    guild_settings = FakeGuildSettingsRepository(
        [
            GuildSettings(
                guild_id=guild.id,
                voice_channel_id=bot_channel.id,
                selected_category="chill",
                volume=0.01,
                stay_connected=True,
                panel_channel_id=None,
                panel_message_id=None,
            )
        ]
    )
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    now = bot_module.time.monotonic()
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.settings = type("FakeSettings", (), {"default_category": "chill"})()
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    bot._last_gateway_recoverable_disconnect_at = now
    bot._last_user_requested_disconnect_at_by_guild = {guild.id: now}

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.connected == []
    assert player_manager.started == []
    assert player_manager.external_disconnect_calls == [guild.id]
    assert refreshed == [guild.id]


def test_stay_connected_reconnect_delay_uses_exponential_backoff(monkeypatch) -> None:
    monkeypatch.setattr(bot_module, "STAY_CONNECTED_RECONNECT_BASE_DELAY_SECONDS", 5.0)
    monkeypatch.setattr(bot_module, "STAY_CONNECTED_RECONNECT_MAX_DELAY_SECONDS", 30.0)

    assert bot_module._stay_connected_reconnect_delay(1) == 5.0
    assert bot_module._stay_connected_reconnect_delay(2) == 10.0
    assert bot_module._stay_connected_reconnect_delay(3) == 20.0
    assert bot_module._stay_connected_reconnect_delay(4) == 30.0
    assert bot_module._stay_connected_reconnect_delay(5) == 30.0


def test_gateway_recoverable_disconnect_log_handler_records_5xx() -> None:
    recorded = []
    handler = bot_module.DiscordGatewayRecoverableDisconnectLogHandler(
        lambda: recorded.append(True),
    )

    for status in (500, 502, 503, 599):
        error = SimpleNamespace(status=status)
        record = bot_module.logging.LogRecord(
            name="discord.client",
            level=bot_module.logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Attempting a reconnect",
            args=(),
            exc_info=(type(error), error, None),
        )
        handler.emit(record)

    assert recorded == [True, True, True, True]


def test_gateway_recoverable_disconnect_log_handler_records_session_invalidation() -> None:
    recorded = []
    handler = bot_module.DiscordGatewayRecoverableDisconnectLogHandler(
        lambda: recorded.append(True),
    )
    record = bot_module.logging.LogRecord(
        name="discord.gateway",
        level=bot_module.logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Shard ID None session has been invalidated.",
        args=(),
        exc_info=None,
    )

    handler.emit(record)

    assert recorded == [True]


def test_gateway_recoverable_disconnect_log_handler_ignores_non_5xx() -> None:
    recorded = []
    handler = bot_module.DiscordGatewayRecoverableDisconnectLogHandler(
        lambda: recorded.append(True),
    )

    for status in (400, 401, 429, 600):
        error = SimpleNamespace(status=status)
        record = bot_module.logging.LogRecord(
            name="discord.client",
            level=bot_module.logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Attempting a reconnect",
            args=(),
            exc_info=(type(error), error, None),
        )
        handler.emit(record)

    assert recorded == []


async def test_voice_state_update_ignores_self_disconnect_during_shutdown(monkeypatch) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=None)
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    bot._shutting_down = True

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )

    assert getattr(bot, "_self_voice_recovery_tasks", {}) == {}
    assert player_manager.external_disconnect_calls == []
    assert player_manager.connected == []
    assert player_manager.started == []
    assert refreshed == []


async def test_begin_shutdown_cancels_pending_self_voice_recovery() -> None:
    bot = object.__new__(LofiDiscordBot)

    async def recover() -> None:
        await bot_module.asyncio.Event().wait()

    recovery_task = bot_module.asyncio.create_task(recover())
    await bot_module.asyncio.sleep(0)
    bot._self_voice_recovery_tasks = {123: recovery_task}

    LofiDiscordBot.begin_shutdown(bot)
    with suppress(bot_module.asyncio.CancelledError):
        await recovery_task

    assert bot._shutting_down is True
    assert recovery_task.cancelled()


async def test_voice_state_update_ignores_self_disconnect_after_leave_already_handled(
    monkeypatch,
) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=None)
    player_manager = FakePlayerManager()
    player_manager.externally_disconnected = False
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.external_disconnect_calls == [guild.id]
    assert refreshed == []


async def test_voice_state_update_recovers_self_disconnect_after_voice_reconnect(
    monkeypatch,
) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    guild = FakeGuild(123, voice_client=FakeBotVoiceClient(bot_channel))
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0)

    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]

    assert player_manager.external_disconnect_calls == []
    assert player_manager.connected == [(guild.id, bot_channel.id)]
    assert player_manager.restarted == [guild.id]
    assert refreshed == [guild.id]


async def test_voice_state_update_waits_for_in_progress_voice_reconnect(
    monkeypatch,
) -> None:
    bot_user_id = 999
    bot_channel = FakeVoiceChannel(456)
    voice_client = FakeBotVoiceClient(bot_channel, connected=False)
    guild = FakeGuild(123, voice_client=voice_client)
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot._connection = SimpleNamespace(user=SimpleNamespace(id=bot_user_id))
    bot._refresh_panel_message = _noop_refresh_panel
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS", 0)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(bot_module, "SELF_VOICE_RECOVERY_POLL_SECONDS", 0.01)

    async def finish_reconnect() -> None:
        await bot_module.asyncio.sleep(0.02)
        voice_client.connected = True

    reconnect_task = bot_module.asyncio.create_task(finish_reconnect())
    await LofiDiscordBot.on_voice_state_update(
        bot,
        FakeVoiceMember(guild, bot=True, member_id=bot_user_id),
        FakeVoiceState(bot_channel),
        FakeVoiceState(None),
    )
    recovery_tasks = list(bot._self_voice_recovery_tasks.values())
    assert len(recovery_tasks) == 1
    await recovery_tasks[0]
    await reconnect_task

    assert player_manager.external_disconnect_calls == []
    assert player_manager.connected == [(guild.id, bot_channel.id)]
    assert player_manager.restarted == [guild.id]


def test_member_switchable_commands_are_not_discord_admin_locked() -> None:
    bot = object.__new__(LofiDiscordBot)
    commands = [
        bot_module.app_commands.Command(
            name="play",
            description="BGMの再生/停止を切り替えて操作パネルを表示します",
            callback=bot._play_command,
        ),
        bot_module.app_commands.Command(
            name="volume",
            description="音量を変更します",
            callback=bot._volume_command,
        ),
        bot_module.app_commands.Command(
            name="stay",
            description="Stayを切り替えます",
            callback=bot._stay_command,
        ),
        bot_module.app_commands.Command(
            name="leave",
            description="VCから退出します",
            callback=bot._leave_command,
        ),
        bot_module.app_commands.Command(
            name="voice_event_sounds",
            description="入退室音を切り替えます",
            callback=bot._voice_event_sounds_command,
        ),
    ]
    member_commands = bot_module.app_commands.Command(
        name="member_commands",
        description="メンバーのコマンド利用を切り替えます（管理者のみ）",
        callback=bot._member_commands_command,
    )

    assert all(command.default_permissions is None for command in commands)
    assert member_commands.default_permissions is not None
    assert member_commands.default_permissions.administrator


async def test_play_command_connects_and_posts_panel_for_admin(monkeypatch) -> None:
    guild_settings = FakeGuildSettingsRepository([])
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.guild_settings = guild_settings
    bot.player_manager = player_manager
    bot.settings = type("FakeSettings", (), {"default_category": "chill"})()
    channel = FakeVoiceChannel(456)
    interaction = FakeInteraction(
        guild_id=123,
        administrator=True,
        user=FakeCommandMember(channel),
    )
    monkeypatch.setattr(bot_module.discord, "Member", FakeCommandMember)
    monkeypatch.setattr(bot_module.discord, "VoiceChannel", FakeVoiceChannel)

    await LofiDiscordBot._play_command(bot, interaction)

    assert interaction.response.deferred is True
    assert player_manager.connected == [(123, 456)]
    assert player_manager.started == [123]
    assert len(interaction.followup.messages) == 1
    assert guild_settings.panel_updates == [(123, 456, 789)]


async def test_play_command_toggles_disconnect_for_admin(monkeypatch) -> None:
    player_manager = FakePlayerManager()
    refreshed: list[int] = []
    channel = FakeVoiceChannel(456)
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    interaction = FakeInteraction(
        guild_id=123,
        administrator=True,
        user=FakeCommandMember(channel),
        voice_client=FakeBotVoiceClient(channel),
    )
    monkeypatch.setattr(bot_module.discord, "Member", FakeCommandMember)

    await LofiDiscordBot._play_command(bot, interaction)

    assert player_manager.leave_calls == [(123, True, True)]
    assert player_manager.connected == []
    assert player_manager.started == []
    assert refreshed == [123]
    assert 123 in bot._last_user_requested_disconnect_at_by_guild
    assert interaction.response.messages == [("VCから退出しました。", True)]


async def test_play_command_disconnects_voice_client_without_player(monkeypatch) -> None:
    player_manager = FakePlayerManager()
    player_manager.left = False
    refreshed: list[int] = []
    channel = FakeVoiceChannel(456)
    voice_client = FakeBotVoiceClient(channel)
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    interaction = FakeInteraction(
        guild_id=123,
        administrator=True,
        user=FakeCommandMember(channel),
        voice_client=voice_client,
    )
    monkeypatch.setattr(bot_module.discord, "Member", FakeCommandMember)

    await LofiDiscordBot._play_command(bot, interaction)

    assert player_manager.leave_calls == [(123, True, True)]
    assert voice_client.disconnect_calls == [True]
    assert refreshed == [123]
    assert 123 in bot._last_user_requested_disconnect_at_by_guild
    assert interaction.response.messages == [("VCから退出しました。", True)]


async def test_play_command_rejects_non_admin(monkeypatch) -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    _set_member_command_access(bot)
    channel = FakeVoiceChannel(456)
    interaction = FakeInteraction(
        guild_id=123,
        administrator=False,
        user=FakeCommandMember(channel),
    )
    monkeypatch.setattr(bot_module.discord, "Member", FakeCommandMember)

    await LofiDiscordBot._play_command(bot, interaction)

    assert player_manager.connected == []
    assert player_manager.leave_calls == []
    assert interaction.response.messages == [
        ("BGM再生は現在管理者のみ使えます。", True),
    ]


async def test_volume_command_rejects_non_admin() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    _set_member_command_access(bot)
    refreshed: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._volume_command(bot, interaction, 50)

    assert player_manager.volumes == []
    assert refreshed == []
    assert interaction.response.messages == [
        ("音量変更は現在管理者のみ使えます。", True),
    ]


async def test_volume_command_allows_member_when_member_commands_are_enabled() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    _set_member_command_access(bot, member_commands_enabled=True)
    refreshed: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._volume_command(bot, interaction, 42)

    assert player_manager.volumes == [(123, 0.42)]
    assert refreshed == [123]
    assert interaction.response.messages == [
        ("音量を 42% にしました。", True),
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
    _set_member_command_access(bot)
    bot._refresh_panel_message = _noop_refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._stay_command(bot, interaction)

    assert player_manager.stay_connected == []
    assert player_manager.leave_if_alone_calls == []
    assert interaction.response.messages == [
        ("Stay変更は現在管理者のみ使えます。", True),
    ]


async def test_stay_command_turns_on_for_admin() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    refreshed: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    bot._refresh_panel_message = refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=True)

    await LofiDiscordBot._stay_command(bot, interaction)

    assert player_manager.stay_connected == [(123, True)]
    assert player_manager.leave_if_alone_calls == []
    assert refreshed == [123]
    assert interaction.response.messages == [
        ("Stayを ON にしました。", True),
    ]


async def test_stay_command_turns_off_and_leaves_if_alone_for_admin() -> None:
    player_manager = FakePlayerManager()
    player_manager.current_stay_connected = True
    player_manager.left_alone = True
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    bot._refresh_panel_message = _noop_refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=True)

    await LofiDiscordBot._stay_command(bot, interaction)

    assert player_manager.stay_connected == [(123, False)]
    assert player_manager.leave_if_alone_calls == [123]
    assert interaction.response.messages == [
        ("Stayを OFF にしました。 VCが空だったため退出しました。", True),
    ]


async def test_leave_command_rejects_non_admin() -> None:
    player_manager = FakePlayerManager()
    bot = object.__new__(LofiDiscordBot)
    bot.player_manager = player_manager
    _set_member_command_access(bot)
    bot._refresh_panel_message = _noop_refresh_panel
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._leave_command(bot, interaction)

    assert player_manager.leave_calls == []
    assert interaction.response.messages == [
        ("VC退出は現在管理者のみ使えます。", True),
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
    assert 123 in bot._last_user_requested_disconnect_at_by_guild
    assert interaction.response.messages == [
        ("VCから退出しました。", True),
    ]


async def test_member_commands_command_rejects_non_admin() -> None:
    bot = object.__new__(LofiDiscordBot)
    _set_member_command_access(bot)
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._member_commands_command(bot, interaction)

    assert bot.guild_settings.member_command_updates == []
    assert interaction.response.messages == [
        ("メンバーのコマンド利用を変更できるのは管理者だけです。", True),
    ]


async def test_member_commands_command_turns_on_for_admin() -> None:
    bot = object.__new__(LofiDiscordBot)
    guild_settings = _set_member_command_access(bot)
    interaction = FakeInteraction(guild_id=123, administrator=True)

    await LofiDiscordBot._member_commands_command(bot, interaction)

    assert guild_settings.member_command_updates == [(123, True)]
    assert interaction.response.messages == [
        ("メンバーのコマンド利用を ON にしました。", True),
    ]


async def test_member_commands_command_turns_off_for_admin() -> None:
    bot = object.__new__(LofiDiscordBot)
    guild_settings = _set_member_command_access(bot, member_commands_enabled=True)
    interaction = FakeInteraction(guild_id=123, administrator=True)

    await LofiDiscordBot._member_commands_command(bot, interaction)

    assert guild_settings.member_command_updates == [(123, False)]
    assert interaction.response.messages == [
        ("メンバーのコマンド利用を OFF にしました。", True),
    ]


async def test_voice_event_sounds_command_turns_on_for_member() -> None:
    bot = object.__new__(LofiDiscordBot)
    guild_settings = _set_voice_event_sounds_access(bot)
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._voice_event_sounds_command(bot, interaction)

    assert guild_settings.voice_event_sound_updates == [(123, True)]
    assert interaction.response.messages == [
        ("入退室音を ON にしました。", True),
    ]


async def test_voice_event_sounds_command_rejects_dm() -> None:
    bot = object.__new__(LofiDiscordBot)
    guild_settings = _set_voice_event_sounds_access(bot)
    interaction = FakeInteraction(guild_id=None, administrator=False)

    await LofiDiscordBot._voice_event_sounds_command(bot, interaction)

    assert guild_settings.voice_event_sound_updates == []
    assert interaction.response.messages == [
        ("サーバー内で使ってください。", True),
    ]


async def test_voice_event_sounds_command_turns_off_for_member() -> None:
    bot = object.__new__(LofiDiscordBot)
    guild_settings = _set_voice_event_sounds_access(
        bot,
        voice_event_sounds_enabled=True,
    )
    interaction = FakeInteraction(guild_id=123, administrator=False)

    await LofiDiscordBot._voice_event_sounds_command(bot, interaction)

    assert guild_settings.voice_event_sound_updates == [(123, False)]
    assert interaction.response.messages == [
        ("入退室音を OFF にしました。", True),
    ]


async def _noop_refresh_panel(guild_id: int) -> None:
    pass
