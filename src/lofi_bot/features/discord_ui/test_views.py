from __future__ import annotations

from lofi_bot.features.catalog.models import Track
from lofi_bot.features.discord_ui.views import (
    PlayerControlView,
    build_panel_embed,
    format_duration,
    format_progress_bar,
)
from lofi_bot.features.guild_settings.repository import GuildSettings


class FakeGuildSettingsRepository:
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


class FakePlayerManager:
    def __init__(self, track: Track | None = None, elapsed_seconds: int | None = None) -> None:
        self.track = track
        self.elapsed_seconds = elapsed_seconds

    def current_track(self, guild_id: int):
        return self.track

    def current_track_elapsed_seconds(self, guild_id: int) -> int | None:
        return self.elapsed_seconds


async def test_panel_embed_includes_source_link_without_category_field() -> None:
    embed = await build_panel_embed(
        guild_id=123,
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(),
        default_category="chill",
    )

    fields = {field.name: field.value for field in embed.fields}

    assert "Category" not in fields
    assert "Volume" not in fields
    assert fields["Source"] == (
        "[Jamendo: Chill](https://www.jamendo.com/search?qs=q%3Dchill+relaxation+calm+instrumental)"
    )
    assert fields["Stay"] == "OFF"
    assert fields["Now Playing"] == "準備中"
    assert "Progress" not in fields


async def test_panel_embed_includes_progress_bar_for_current_track() -> None:
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
        player_manager=FakePlayerManager(track=track, elapsed_seconds=50),
        default_category="chill",
    )

    fields = {field.name: field.value for field in embed.fields}

    assert fields["Now Playing"] == "[Morning Loop](https://example.com/track)\nby Cafe Artist"
    assert fields["Progress"] == "`#####---------------` 0:50 / 3:20"


def test_format_duration() -> None:
    assert format_duration(0) == "0:00"
    assert format_duration(65) == "1:05"


def test_format_progress_bar_clamps_elapsed_time() -> None:
    assert format_progress_bar(120, 60) == "`####################` 1:00 / 1:00"


def test_player_control_view_only_includes_skip_button() -> None:
    view = PlayerControlView(
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(),
    )

    assert [item.custom_id for item in view.children] == [
        "lofi_bot:skip",
    ]
