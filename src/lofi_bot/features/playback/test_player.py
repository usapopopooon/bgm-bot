from __future__ import annotations

import asyncio

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
        category_slug="lofi",
        volume=0.01,
        on_track_changed=refresh_panel,
    )

    player._set_current_track(None)
    await asyncio.sleep(0)

    assert calls == [123]
