from __future__ import annotations

from types import SimpleNamespace

from lofi_bot.features.playback.manager import PlayerManager


class FakeSettingsRepository:
    def __init__(
        self,
        stay_connected: bool = False,
        voice_channel_id: int | None = None,
    ) -> None:
        self.stay_connected = stay_connected
        self.voice_channel_id = voice_channel_id
        self.voice_channel_updates: list[tuple[int, int]] = []
        self.selected_categories: list[tuple[int, str]] = []
        self.volumes: list[tuple[int, float]] = []
        self.stay_updates: list[tuple[int, bool]] = []
        self.cleared_voice_channels: list[int] = []

    async def get_or_create(self, guild_id: int, default_category: str):
        return SimpleNamespace(
            voice_channel_id=self.voice_channel_id,
            selected_category=default_category,
            volume=0.01,
            stay_connected=self.stay_connected,
        )

    async def update_voice_channel(self, guild_id: int, voice_channel_id: int) -> None:
        self.voice_channel_id = voice_channel_id
        self.voice_channel_updates.append((guild_id, voice_channel_id))

    async def update_selected_category(self, guild_id: int, category_slug: str) -> None:
        self.selected_categories.append((guild_id, category_slug))

    async def update_volume(self, guild_id: int, volume: float) -> None:
        self.volumes.append((guild_id, volume))

    async def update_stay_connected(self, guild_id: int, stay_connected: bool) -> None:
        self.stay_connected = stay_connected
        self.stay_updates.append((guild_id, stay_connected))

    async def clear_voice_channel(self, guild_id: int) -> None:
        self.cleared_voice_channels.append(guild_id)


class FakeCatalogService:
    def __init__(self) -> None:
        self.refreshed_categories: list[str] = []

    async def refresh_category(self, category_slug: str) -> bool:
        self.refreshed_categories.append(category_slug)
        return True


class FakePlayer:
    def __init__(self, is_active: bool) -> None:
        self.is_active = is_active
        self.skipped = False
        self.stopped = False
        self.category_slug: str | None = None
        self.volume: float | None = None
        self.track_changed_callback = None
        self.current_track = None
        self.is_paused = False
        self.pause_toggled = False
        self.restarted_after_reconnect = False

    async def stop(self) -> None:
        self.stopped = True

    async def skip(self) -> None:
        self.skipped = True

    async def toggle_pause(self) -> bool:
        self.pause_toggled = True
        self.is_paused = not self.is_paused
        return True

    async def restart_after_reconnect(self) -> None:
        self.restarted_after_reconnect = True

    async def set_category(self, category_slug: str) -> None:
        self.category_slug = category_slug

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def set_track_changed_callback(self, callback) -> None:
        self.track_changed_callback = callback


class FakeConnectVoiceChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.connect_calls: list[dict[str, object]] = []
        self.voice_client = FakeConnectedVoiceClient(self)

    async def connect(self, **kwargs: object) -> FakeConnectedVoiceClient:
        self.connect_calls.append(kwargs)
        return self.voice_client


class FakeConnectedVoiceClient:
    def __init__(self, channel: FakeConnectVoiceChannel, connected: bool = True) -> None:
        self.channel = channel
        self._connected = connected
        self.move_calls: list[FakeConnectVoiceChannel] = []

    def is_connected(self) -> bool:
        return self._connected

    async def move_to(self, channel: FakeConnectVoiceChannel) -> None:
        self.channel = channel
        self.move_calls.append(channel)


class FakeConnectGuild:
    def __init__(self, voice_client: FakeConnectedVoiceClient | None = None) -> None:
        self.id = 123
        self.voice_client = voice_client
        self.voice_state_changes: list[dict[str, object]] = []

    async def change_voice_state(self, **kwargs: object) -> None:
        self.voice_state_changes.append(kwargs)


async def test_connect_self_deafens_new_voice_connection() -> None:
    settings = FakeSettingsRepository()
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    guild = FakeConnectGuild()
    channel = FakeConnectVoiceChannel(456)

    player = await manager.connect(guild, channel)

    assert player.voice_client is channel.voice_client
    assert channel.connect_calls == [
        {
            "reconnect": True,
            "timeout": 20,
            "self_deaf": True,
        }
    ]
    assert settings.voice_channel_updates == [(123, 456)]


async def test_connect_wires_catalog_refresh_callback_to_player() -> None:
    settings = FakeSettingsRepository()
    catalog_service = FakeCatalogService()
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
        catalog_service=catalog_service,
    )
    guild = FakeConnectGuild()
    channel = FakeConnectVoiceChannel(456)

    player = await manager.connect(guild, channel)
    refreshed = await player._refresh_catalog("chill")

    assert refreshed is True
    assert catalog_service.refreshed_categories == ["chill"]


async def test_connect_reapplies_speaker_mute_for_existing_voice_connection() -> None:
    channel = FakeConnectVoiceChannel(456)
    voice_client = FakeConnectedVoiceClient(channel)
    settings = FakeSettingsRepository(voice_channel_id=channel.id)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    guild = FakeConnectGuild(voice_client)

    player = await manager.connect(guild, channel)

    assert player.voice_client is voice_client
    assert channel.connect_calls == []
    assert voice_client.move_calls == []
    assert guild.voice_state_changes == [
        {
            "channel": channel,
            "self_deaf": True,
            "self_mute": False,
        }
    ]
    assert settings.voice_channel_updates == []


async def test_connect_moves_existing_voice_connection_before_speaker_mute() -> None:
    old_channel = FakeConnectVoiceChannel(111)
    new_channel = FakeConnectVoiceChannel(456)
    voice_client = FakeConnectedVoiceClient(old_channel)
    settings = FakeSettingsRepository(voice_channel_id=old_channel.id)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    guild = FakeConnectGuild(voice_client)

    await manager.connect(guild, new_channel)

    assert voice_client.move_calls == [new_channel]
    assert guild.voice_state_changes == [
        {
            "channel": new_channel,
            "self_deaf": True,
            "self_mute": False,
        }
    ]
    assert settings.voice_channel_updates == [(123, 456)]


async def test_skip_returns_false_for_disconnected_player() -> None:
    manager = PlayerManager(
        tracks=None,
        guild_settings=FakeSettingsRepository(),
        default_category="chill",
    )
    player = FakePlayer(is_active=False)
    manager._players[123] = player

    result = await manager.skip(123)

    assert result is False
    assert player.skipped is False


async def test_toggle_pause_returns_false_for_disconnected_player() -> None:
    manager = PlayerManager(
        tracks=None,
        guild_settings=FakeSettingsRepository(),
        default_category="chill",
    )
    player = FakePlayer(is_active=False)
    manager._players[123] = player

    result = await manager.toggle_pause(123)

    assert result is False
    assert player.pause_toggled is False


async def test_toggle_pause_updates_active_player() -> None:
    manager = PlayerManager(
        tracks=None,
        guild_settings=FakeSettingsRepository(),
        default_category="chill",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player

    result = await manager.toggle_pause(123)

    assert result is True
    assert player.pause_toggled is True
    assert manager.is_paused(123) is True


async def test_set_category_still_persists_but_does_not_play_disconnected_player() -> None:
    settings = FakeSettingsRepository()
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    player = FakePlayer(is_active=False)
    manager._players[123] = player

    result = await manager.set_category(123, "chill")

    assert result is False
    assert settings.selected_categories == [(123, "chill")]
    assert player.category_slug is None


async def test_set_volume_persists_and_applies_for_active_player() -> None:
    settings = FakeSettingsRepository()
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player

    result = await manager.set_volume(123, 0.8)

    assert result is True
    assert settings.volumes == [(123, 0.8)]
    assert player.volume == 0.8


async def test_set_volume_persists_but_does_not_apply_for_disconnected_player() -> None:
    settings = FakeSettingsRepository()
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    player = FakePlayer(is_active=False)
    manager._players[123] = player

    result = await manager.set_volume(123, 1.5)

    assert result is False
    assert settings.volumes == [(123, 1.0)]
    assert player.volume is None


async def test_set_track_changed_callback_updates_existing_players() -> None:
    manager = PlayerManager(
        tracks=None,
        guild_settings=FakeSettingsRepository(),
        default_category="chill",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player

    async def refresh_panel(guild_id: int) -> None:
        return None

    manager.set_track_changed_callback(refresh_panel)

    assert player.track_changed_callback is refresh_panel


async def test_restart_after_reconnect_restarts_existing_player() -> None:
    manager = PlayerManager(
        tracks=None,
        guild_settings=FakeSettingsRepository(),
        default_category="chill",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player
    guild = SimpleNamespace(id=123)

    await manager.restart_after_reconnect(guild)

    assert player.restarted_after_reconnect is True


class FakeMember:
    def __init__(self, *, bot: bool) -> None:
        self.bot = bot


class FakeVoiceChannel:
    def __init__(self, members: list[FakeMember]) -> None:
        self.members = members


class FakeVoiceClient:
    def __init__(self, members: list[FakeMember], connected: bool = True) -> None:
        self.channel = FakeVoiceChannel(members)
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected


class FakeGuild:
    def __init__(self, voice_client: FakeVoiceClient | None) -> None:
        self.id = 123
        self.voice_client = voice_client


async def test_leave_if_alone_disconnects_when_only_bots_remain() -> None:
    settings = FakeSettingsRepository(stay_connected=False)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player
    refreshed: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        refreshed.append(guild_id)

    manager.set_track_changed_callback(refresh_panel)
    guild = FakeGuild(FakeVoiceClient([FakeMember(bot=True)]))

    result = await manager.leave_if_alone(guild)

    assert result is True
    assert player.stopped is True
    assert manager._players == {}
    assert refreshed == [123]
    assert settings.cleared_voice_channels == [123]


async def test_leave_if_alone_keeps_connected_when_stay_is_enabled() -> None:
    settings = FakeSettingsRepository(stay_connected=True)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player
    guild = FakeGuild(FakeVoiceClient([FakeMember(bot=True)]))

    result = await manager.leave_if_alone(guild)

    assert result is False
    assert player.stopped is False
    assert manager._players == {123: player}


async def test_leave_if_alone_keeps_connected_when_humans_remain() -> None:
    settings = FakeSettingsRepository(stay_connected=False)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player
    guild = FakeGuild(FakeVoiceClient([FakeMember(bot=True), FakeMember(bot=False)]))

    result = await manager.leave_if_alone(guild)

    assert result is False
    assert player.stopped is False
    assert manager._players == {123: player}


async def test_set_stay_connected_persists_setting() -> None:
    settings = FakeSettingsRepository()
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )

    await manager.set_stay_connected(123, True)

    assert settings.stay_updates == [(123, True)]


async def test_get_stay_connected_reads_setting() -> None:
    settings = FakeSettingsRepository(stay_connected=True)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )

    assert await manager.get_stay_connected(123) is True


async def test_manual_leave_can_clear_saved_channel_and_disable_stay() -> None:
    settings = FakeSettingsRepository(stay_connected=True)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player

    result = await manager.leave(
        123,
        clear_saved_channel=True,
        disable_stay_connected=True,
    )

    assert result is True
    assert player.stopped is True
    assert settings.cleared_voice_channels == [123]
    assert settings.stay_updates == [(123, False)]


async def test_manual_leave_clears_saved_session_even_when_not_connected() -> None:
    settings = FakeSettingsRepository(stay_connected=True)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )

    result = await manager.leave(
        123,
        clear_saved_channel=True,
        disable_stay_connected=True,
    )

    assert result is False
    assert settings.cleared_voice_channels == [123]
    assert settings.stay_updates == [(123, False)]


async def test_external_disconnect_clears_saved_session_and_disables_stay() -> None:
    settings = FakeSettingsRepository(stay_connected=True)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player

    result = await manager.handle_external_disconnect(123)

    assert result is True
    assert player.stopped is True
    assert manager._players == {}
    assert settings.cleared_voice_channels == [123]
    assert settings.stay_updates == [(123, False)]


async def test_external_disconnect_ignores_already_removed_player() -> None:
    settings = FakeSettingsRepository(stay_connected=True)
    manager = PlayerManager(
        tracks=None,
        guild_settings=settings,
        default_category="chill",
    )

    result = await manager.handle_external_disconnect(123)

    assert result is False
    assert settings.cleared_voice_channels == []
    assert settings.stay_updates == []
