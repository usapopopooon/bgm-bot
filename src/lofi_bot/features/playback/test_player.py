from __future__ import annotations

import asyncio

from lofi_bot.features.catalog.models import Track
from lofi_bot.features.playback.player import GuildPlayer


class FakeVoiceClient:
    def __init__(
        self,
        *,
        play_raises: bool = False,
        playing: bool = False,
        paused: bool = False,
    ) -> None:
        self.play_raises = play_raises
        self.played_sources: list[object] = []
        self._playing = playing
        self._paused = paused
        self.pause_calls = 0
        self.resume_calls = 0

    def is_connected(self) -> bool:
        return True

    def is_playing(self) -> bool:
        return self._playing

    def is_paused(self) -> bool:
        return self._paused

    def play(self, source: object, *, after) -> None:  # noqa: ANN001
        if self.play_raises:
            raise RuntimeError("cannot play")
        self.played_sources.append(source)
        self._playing = True
        self._paused = False

    def pause(self) -> None:
        self.pause_calls += 1
        self._playing = False
        self._paused = True

    def resume(self) -> None:
        self.resume_calls += 1
        self._playing = True
        self._paused = False

    def stop(self) -> None:
        self._playing = False
        self._paused = False


class FakeTrackRepository:
    def __init__(self, tracks: list[Track]) -> None:
        self.tracks = tracks
        self.index = 0
        self.random_results: list[Track | None] | None = None
        self.any_track: Track | None = None
        self.recorded: list[int] = []
        self.failed: list[int] = []
        self.reset_calls: list[tuple[int, str]] = []

    async def get_random_track(self, guild_id: int, category_slug: str) -> Track | None:
        if self.random_results is not None:
            return self.random_results.pop(0)
        if self.index >= len(self.tracks):
            return None
        track = self.tracks[self.index]
        self.index += 1
        return track

    async def get_any_random_track(self, category_slug: str) -> Track | None:
        return self.any_track

    async def record_play(self, guild_id: int, track_id: int, category_slug: str) -> None:
        self.recorded.append(track_id)

    async def reset_play_history(self, guild_id: int, category_slug: str) -> None:
        self.reset_calls.append((guild_id, category_slug))

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


async def test_toggle_pause_pauses_and_resumes_playback() -> None:
    voice_client = FakeVoiceClient(playing=True)
    player = GuildPlayer(
        guild_id=123,
        voice_client=voice_client,
        tracks=None,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
    )

    paused = await player.toggle_pause()

    assert paused is True
    assert voice_client.pause_calls == 1
    assert player.is_paused is True

    resumed = await player.toggle_pause()

    assert resumed is True
    assert voice_client.resume_calls == 1
    assert player.is_paused is False


async def test_toggle_pause_returns_false_when_not_playing() -> None:
    voice_client = FakeVoiceClient()
    player = GuildPlayer(
        guild_id=123,
        voice_client=voice_client,
        tracks=None,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
    )

    toggled = await player.toggle_pause()

    assert toggled is False
    assert voice_client.pause_calls == 0
    assert voice_client.resume_calls == 0


async def test_play_next_only_notifies_once_when_replacing_current_track() -> None:
    calls: list[int] = []

    async def refresh_panel(guild_id: int) -> None:
        calls.append(guild_id)

    repository = FakeTrackRepository([make_track(1)])
    player = GuildPlayer(
        guild_id=123,
        voice_client=FakeVoiceClient(),
        tracks=repository,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
        on_track_changed=refresh_panel,
    )
    player._create_source = lambda track: object()
    player.current_track = make_track(99, title="Old Track")

    await player.play_next()
    await asyncio.sleep(0)

    assert player.current_track == repository.tracks[0]
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


async def test_restart_after_reconnect_stops_stale_player_before_next_track() -> None:
    voice_client = FakeVoiceClient(playing=True)
    repository = FakeTrackRepository([make_track(1)])
    player = GuildPlayer(
        guild_id=123,
        voice_client=voice_client,
        tracks=repository,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
    )
    player._create_source = lambda track: object()

    await player.restart_after_reconnect()

    assert len(voice_client.played_sources) == 1
    assert player.current_track == repository.tracks[0]
    assert repository.recorded == [1]


async def test_play_next_refreshes_catalog_when_cycle_is_exhausted() -> None:
    refreshes: list[str] = []
    repository = FakeTrackRepository([])
    repository.random_results = [None, make_track(1)]

    async def refresh_catalog(category_slug: str) -> bool:
        refreshes.append(category_slug)
        return True

    player = GuildPlayer(
        guild_id=123,
        voice_client=FakeVoiceClient(),
        tracks=repository,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
        refresh_catalog=refresh_catalog,
    )
    player._create_source = lambda track: object()

    await player.play_next()

    assert refreshes == ["chill"]
    assert player.current_track is not None
    assert player.current_track.id == 1
    assert repository.reset_calls == []
    assert repository.recorded == [1]


async def test_play_next_resets_cycle_when_refresh_returns_no_tracks() -> None:
    repository = FakeTrackRepository([])
    repository.random_results = [None, make_track(2)]
    player = GuildPlayer(
        guild_id=123,
        voice_client=FakeVoiceClient(),
        tracks=repository,
        guild_settings=None,
        category_slug="chill",
        volume=0.01,
    )
    player._create_source = lambda track: object()

    await player.play_next()

    assert repository.reset_calls == [(123, "chill")]
    assert player.current_track is not None
    assert player.current_track.id == 2
    assert repository.recorded == [2]


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
