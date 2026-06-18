from __future__ import annotations

import asyncio

from lofi_bot.features.catalog.models import Track
from lofi_bot.features.playback.player import GuildPlayer


class FakeVoiceClient:
    def __init__(self, *, play_raises: bool = False) -> None:
        self.play_raises = play_raises
        self.played_sources: list[object] = []

    def is_connected(self) -> bool:
        return True

    def is_playing(self) -> bool:
        return False

    def is_paused(self) -> bool:
        return False

    def play(self, source: object, *, after) -> None:  # noqa: ANN001
        if self.play_raises:
            raise RuntimeError("cannot play")
        self.played_sources.append(source)


class FakeTrackRepository:
    def __init__(self, tracks: list[Track]) -> None:
        self.tracks = tracks
        self.index = 0
        self.recorded: list[int] = []
        self.failed: list[int] = []

    async def get_random_track(self, guild_id: int, category_slug: str) -> Track | None:
        if self.index >= len(self.tracks):
            return None
        track = self.tracks[self.index]
        self.index += 1
        return track

    async def record_play(self, guild_id: int, track_id: int, category_slug: str) -> None:
        self.recorded.append(track_id)

    async def mark_failed(self, track_id: int) -> None:
        self.failed.append(track_id)


def make_track(track_id: int, title: str = "Track") -> Track:
    return Track(
        id=track_id,
        provider_track_id=f"jamendo-{track_id}",
        title=title,
        artist="Artist",
        audio_url="https://example.com/audio.mp3",
        share_url="https://example.com/track",
        license_url=None,
        duration_seconds=100,
        ranking_category="chill",
        rank_position=track_id,
    )


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


async def test_play_next_does_not_leave_stale_current_track_after_play_failures() -> None:
    old_track = make_track(99, title="Old Track")
    tracks = [make_track(index) for index in range(1, 6)]
    repository = FakeTrackRepository(tracks)
    player = GuildPlayer(
        guild_id=123,
        voice_client=FakeVoiceClient(play_raises=True),
        tracks=repository,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
    )
    player._create_source = lambda track: object()
    player._set_current_track(old_track)

    await player.play_next()

    assert player.current_track is None
    assert repository.recorded == [1, 2, 3, 4, 5]
    assert repository.failed == [1, 2, 3, 4, 5]


async def test_track_change_notifications_are_coalesced() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        calls.append(guild_id)
        started.set()
        await release.wait()

    player = GuildPlayer(
        guild_id=123,
        voice_client=FakeVoiceClient(),
        tracks=None,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
        on_track_changed=refresh_panel,
    )

    player._notify_track_changed()
    await started.wait()
    player._notify_track_changed()
    player._notify_track_changed()
    await asyncio.sleep(0)

    assert calls == [123]

    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert calls == [123, 123]
