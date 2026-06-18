from __future__ import annotations

from lofi_bot.features.catalog.models import Track
from lofi_bot.features.discord_ui.views import (
    PlayerControlView,
    build_panel_embed,
)
from lofi_bot.features.guild_settings.repository import GuildSettings


class FakeGuildSettingsRepository:
    def __init__(self) -> None:
        self.get_or_create_calls = 0

    async def get_or_create(self, guild_id: int, default_category: str) -> GuildSettings:
        self.get_or_create_calls += 1
        return GuildSettings(
            guild_id=guild_id,
            voice_channel_id=None,
            selected_category=default_category,
            volume=0.01,
            stay_connected=False,
            panel_channel_id=None,
            panel_message_id=None,
        )


class FakePlayerManager:
    def __init__(self, track: Track | None = None, is_paused: bool = False) -> None:
        self.track = track
        self._is_paused = is_paused

    def current_track(self, guild_id: int):
        return self.track

    def is_paused(self, guild_id: int) -> bool:
        return self._is_paused


async def test_panel_embed_uses_japanese_labels_without_admin_status() -> None:
    guild_settings = FakeGuildSettingsRepository()
    embed = await build_panel_embed(
        guild_id=123,
        guild_settings=guild_settings,
        player_manager=FakePlayerManager(),
        default_category="chill",
    )

    fields = {field.name: field.value for field in embed.fields}

    assert "Category" not in fields
    assert "Volume" not in fields
    assert "Stay" not in fields
    assert embed.title == "BGMボット"
    assert embed.description == "チル系のボーカルなし曲をランダムに再生します。"
    assert fields["検索元"] == "[Jamendo: chill](https://www.jamendo.com/search?q=chill)"
    assert fields["再生中"] == "準備中"
    assert "Progress" not in fields
    assert embed.footer.text == "パネルが流れたら /panel で再投稿できます。"
    assert guild_settings.get_or_create_calls == 0


async def test_panel_embed_includes_current_track_without_progress_bar() -> None:
    track = Track(
        provider_track_id="jamendo-1",
        title="Morning Loop",
        artist="Cafe Artist",
        audio_url="https://example.com/audio.mp3",
        share_url="https://example.com/track",
        license_url=None,
        duration_seconds=200,
        ranking_category="chill",
        rank_position=1,
    )
    embed = await build_panel_embed(
        guild_id=123,
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(track=track),
        default_category="chill",
    )

    fields = {field.name: field.value for field in embed.fields}

    assert fields["再生中"] == "[Morning Loop](https://example.com/track)\nby Cafe Artist"
    assert "Progress" not in fields


def test_player_control_view_includes_pause_and_next_buttons() -> None:
    view = PlayerControlView(
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(),
    )

    assert [item.label for item in view.children] == [
        "一時停止",
        "次の曲へ",
    ]
    assert [item.custom_id for item in view.children] == [
        "lofi_bot:pause",
        "lofi_bot:skip",
    ]


def test_player_control_view_shows_resume_when_paused() -> None:
    view = PlayerControlView(
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(is_paused=True),
        is_paused=True,
    )

    assert [item.label for item in view.children] == [
        "再開",
        "次の曲へ",
    ]
