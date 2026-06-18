from __future__ import annotations

from lofi_bot.features.playback.manager import PlayerManager


class FakeSettingsRepository:
    def __init__(self) -> None:
        self.selected_categories: list[tuple[int, str]] = []
        self.volumes: list[tuple[int, float]] = []

    async def update_selected_category(self, guild_id: int, category_slug: str) -> None:
        self.selected_categories.append((guild_id, category_slug))

    async def update_volume(self, guild_id: int, volume: float) -> None:
        self.volumes.append((guild_id, volume))


class FakePlayer:
    def __init__(self, is_active: bool) -> None:
        self.is_active = is_active
        self.skipped = False
        self.category_slug: str | None = None
        self.volume: float | None = None
        self.track_changed_callback = None

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
        default_category="lofi",
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
        default_category="lofi",
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
        default_category="lofi",
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
        default_category="lofi",
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
        default_category="lofi",
    )
    player = FakePlayer(is_active=True)
    manager._players[123] = player

    async def refresh_panel(guild_id: int) -> None:
        return None

    manager.set_track_changed_callback(refresh_panel)

    assert player.track_changed_callback is refresh_panel
