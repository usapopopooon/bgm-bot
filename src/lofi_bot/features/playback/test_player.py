from __future__ import annotations

import asyncio

from lofi_bot.features.catalog.models import Track
from lofi_bot.features.playback.player import GuildPlayer


class FakeVoiceClient:
    pass


async def test_track_change_notifies_panel_refresh_callback() -> None:
    calls: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        calls.append(guild_id)

    player = GuildPlayer(
        guild_id=123,
        voice_client=FakeVoiceClient(),
        tracks=None,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
        on_track_changed=refresh_panel,
    )

    player._set_current_track(None)
    await asyncio.sleep(0)

    assert calls == [123]


def test_current_track_elapsed_seconds_is_available_for_current_track() -> None:
    player = GuildPlayer(
        guild_id=123,
        voice_client=FakeVoiceClient(),
        tracks=None,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
    )
    track = Track(
        provider_track_id="jamendo-1",
        title="Track",
        artist="Artist",
        audio_url="https://example.com/audio.mp3",
        share_url="https://example.com/track",
        license_url=None,
        duration_seconds=100,
        ranking_category="chill",
        rank_position=1,
    )

    player._set_current_track(track)

    assert player.current_track_elapsed_seconds() is not None

    player._set_current_track(None)

    assert player.current_track_elapsed_seconds() is None
