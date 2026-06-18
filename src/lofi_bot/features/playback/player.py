from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import monotonic

import discord

from lofi_bot.features.catalog.models import Track
from lofi_bot.features.catalog.repository import CatalogRepository
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository

LOGGER = logging.getLogger(__name__)
TrackChangedCallback = Callable[[int], Awaitable[None]]
PROGRESS_REFRESH_INTERVAL_SECONDS = 15.0


def clamp_volume(volume: float) -> float:
    return max(0.0, min(1.0, volume))


class GuildPlayer:
    def __init__(
        self,
        guild_id: int,
        voice_client: discord.VoiceClient,
        tracks: CatalogRepository,
        guild_settings: GuildSettingsRepository,
        category_slug: str,
        volume: float,
        on_track_changed: TrackChangedCallback | None = None,
    ) -> None:
        self.guild_id = guild_id
        self.voice_client = voice_client
        self._tracks = tracks
        self._guild_settings = guild_settings
        self._category_slug = category_slug
        self._volume = clamp_volume(volume)
        self._on_track_changed = on_track_changed
        self._lock = asyncio.Lock()
        self._stopped = False
        self._retry_task: asyncio.Task[None] | None = None
        self._progress_task: asyncio.Task[None] | None = None
        self.current_track: Track | None = None
        self._current_track_started_at: float | None = None

    @property
    def category_slug(self) -> str:
        return self._category_slug

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def is_active(self) -> bool:
        return not self._stopped and self.voice_client.is_connected()

    def current_track_elapsed_seconds(self) -> int | None:
        if self.current_track is None or self._current_track_started_at is None:
            return None
        return max(0, int(monotonic() - self._current_track_started_at))

    def set_volume(self, volume: float) -> None:
        self._volume = clamp_volume(volume)
        source = getattr(self.voice_client, "source", None)
        if isinstance(source, discord.PCMVolumeTransformer):
            source.volume = self._volume

    def set_track_changed_callback(self, callback: TrackChangedCallback | None) -> None:
        self._on_track_changed = callback
        self._restart_progress_updates()

    async def set_category(self, category_slug: str) -> None:
        self._category_slug = category_slug
        await self._guild_settings.update_selected_category(self.guild_id, category_slug)
        self._set_current_track(None)
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()
        else:
            await self.play_next()

    async def skip(self) -> None:
        self._set_current_track(None)
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()
        else:
            await self.play_next()

    async def stop(self) -> None:
        self._stopped = True
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()
        if self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)
        if self._retry_task is not None:
            self._retry_task.cancel()
        self._cancel_progress_updates()

    async def play_next(self) -> None:
        async with self._lock:
            await self._play_next_locked()

    async def _play_next_locked(self) -> None:
        if self._stopped or not self.voice_client.is_connected():
            return
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            return

        for _ in range(5):
            track = await self._tracks.get_random_track(self.guild_id, self._category_slug)
            if track is None or track.id is None:
                self._set_current_track(None)
                LOGGER.warning(
                    "No playable tracks for guild=%s category=%s",
                    self.guild_id,
                    self._category_slug,
                )
                self._schedule_retry()
                return

            try:
                self._cancel_retry()
                source = self._create_source(track)
                self._set_current_track(track)
                await self._tracks.record_play(self.guild_id, track.id, self._category_slug)
                self.voice_client.play(source, after=self._after_play(track))
                LOGGER.info(
                    "Playing guild=%s category=%s track=%s artist=%s",
                    self.guild_id,
                    self._category_slug,
                    track.title,
                    track.artist,
                )
                return
            except Exception:
                LOGGER.exception("Failed to start track id=%s", track.id)
                await self._tracks.mark_failed(track.id)

    def _create_source(self, track: Track) -> discord.AudioSource:
        before_options = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        audio = discord.FFmpegPCMAudio(
            track.audio_url,
            before_options=before_options,
            options="-vn",
        )
        return discord.PCMVolumeTransformer(audio, volume=self._volume)

    def _after_play(self, track: Track):
        loop = asyncio.get_running_loop()

        def callback(error: Exception | None) -> None:
            if error is not None:
                LOGGER.warning(
                    "Playback error guild=%s track=%s: %s",
                    self.guild_id,
                    track.id,
                    error,
                )
                if track.id is not None:
                    loop.call_soon_threadsafe(
                        asyncio.create_task,
                        self._mark_failed_and_continue(track.id),
                    )
                    return
            loop.call_soon_threadsafe(asyncio.create_task, self.play_next())

        return callback

    async def _mark_failed_and_continue(self, track_id: int) -> None:
        await self._tracks.mark_failed(track_id)
        await self.play_next()

    def _schedule_retry(self) -> None:
        if self._retry_task is not None and not self._retry_task.done():
            return
        self._retry_task = asyncio.create_task(self._retry_after_delay())

    def _cancel_retry(self) -> None:
        if self._retry_task is not None and not self._retry_task.done():
            self._retry_task.cancel()

    async def _retry_after_delay(self) -> None:
        try:
            await asyncio.sleep(60)
            await self.play_next()
        except asyncio.CancelledError:
            pass

    def _set_current_track(self, track: Track | None) -> None:
        self.current_track = track
        self._current_track_started_at = monotonic() if track is not None else None
        self._restart_progress_updates()
        self._notify_track_changed()

    def _restart_progress_updates(self) -> None:
        self._cancel_progress_updates()
        if (
            self.current_track is None
            or self.current_track.duration_seconds <= 0
            or self._on_track_changed is None
        ):
            return
        self._progress_task = asyncio.create_task(
            self._refresh_progress_until_track_finishes(self.current_track)
        )

    def _cancel_progress_updates(self) -> None:
        if self._progress_task is not None and not self._progress_task.done():
            self._progress_task.cancel()
        self._progress_task = None

    async def _refresh_progress_until_track_finishes(self, track: Track) -> None:
        try:
            while self.current_track is track and not self._stopped:
                elapsed = self.current_track_elapsed_seconds()
                if elapsed is None:
                    return

                remaining = track.duration_seconds - elapsed
                if remaining <= 0:
                    return

                await asyncio.sleep(min(PROGRESS_REFRESH_INTERVAL_SECONDS, remaining))
                if self.current_track is not track or self._stopped:
                    return
                self._notify_track_changed()
        except asyncio.CancelledError:
            pass

    def _notify_track_changed(self) -> None:
        if self._on_track_changed is None:
            return
        task = asyncio.create_task(self._on_track_changed(self.guild_id))
        task.add_done_callback(self._log_track_changed_error)

    def _log_track_changed_error(self, task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except Exception:
            LOGGER.exception("Failed to refresh panel after track change guild=%s", self.guild_id)
