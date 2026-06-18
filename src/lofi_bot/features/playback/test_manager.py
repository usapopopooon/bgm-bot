from __future__ import annotations

from lofi_bot.features.playback.manager import PlayerManager


class FakeSettingsRepository:
    def __init__(self) -> None:
        self.selected_categories: list[tuple[int, str]] = []

    async def update_selected_category(self, guild_id: int, category_slug: str) -> None:
        self.selected_categories.append((guild_id, category_slug))


class FakePlayer:
    def __init__(self, is_active: bool) -> None:
        self.is_active = is_active
        self.skipped = False
        self.category_slug: str | None = None

    async def skip(self) -> None:
        self.skipped = True

    async def set_category(self, category_slug: str) -> None:
        self.category_slug = category_slug


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
