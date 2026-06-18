from __future__ import annotations

from types import SimpleNamespace

from lofi_bot.features.playback.manager import PlayerManager


class FakeSettingsRepository:
    def __init__(self, stay_connected: bool = False) -> None:
        self.stay_connected = stay_connected
        self.selected_categories: list[tuple[int, str]] = []
        self.volumes: list[tuple[int, float]] = []
        self.stay_updates: list[tuple[int, bool]] = []
        self.cleared_voice_channels: list[int] = []

    async def get_or_create(self, guild_id: int, default_category: str):
        return SimpleNamespace(stay_connected=self.stay_connected)

    async def update_selected_category(self, guild_id: int, category_slug: str) -> None:
        self.selected_categories.append((guild_id, category_slug))

    async def update_volume(self, guild_id: int, volume: float) -> None:
        self.volumes.append((guild_id, volume))

    async def update_stay_connected(self, guild_id: int, stay_connected: bool) -> None:
        self.stay_connected = stay_connected
        self.stay_updates.append((guild_id, stay_connected))

    async def clear_voice_channel(self, guild_id: int) -> None:
        self.cleared_voice_channels.append(guild_id)


class FakePlayer:
    def __init__(self, is_active: bool) -> None:
        self.is_active = is_active
        self.skipped = False
        self.stopped = False
        self.category_slug: str | None = None
        self.volume: float | None = None
        self.track_changed_callback = None
        self.current_track = None

    async def stop(self) -> None:
        self.stopped = True

    async def skip(self) -> None:
        self.skipped = True

    async def set_category(self, category_slug: str) -> None:
        self.category_slug = category_slug

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def set_track_changed_callback(self, callback) -> None:
        self.track_changed_callback = callback


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
