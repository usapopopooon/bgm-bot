from __future__ import annotations

import asyncio
import logging

import discord

from lofi_bot.features.catalog.models import Track
from lofi_bot.features.catalog.repository import CatalogRepository
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository

LOGGER = logging.getLogger(__name__)


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
    ) -> None:
        self.guild_id = guild_id
        self.voice_client = voice_client
        self._tracks = tracks
        self._guild_settings = guild_settings
        self._category_slug = category_slug
        self._volume = clamp_volume(volume)
        self._lock = asyncio.Lock()
        self._stopped = False
        self._retry_task: asyncio.Task[None] | None = None
        self.current_track: Track | None = None

    @property
    def category_slug(self) -> str:
        return self._category_slug

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def is_active(self) -> bool:
        return not self._stopped and self.voice_client.is_connected()

    def set_volume(self, volume: float) -> None:
        self._volume = clamp_volume(volume)
        source = getattr(self.voice_client, "source", None)
        if isinstance(source, discord.PCMVolumeTransformer):
            source.volume = self._volume

    async def set_category(self, category_slug: str) -> None:
        self._category_slug = category_slug
        await self._guild_settings.update_selected_category(self.guild_id, category_slug)
        self.current_track = None
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()
        else:
            await self.play_next()

    async def skip(self) -> None:
        self.current_track = None
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
                self.current_track = None
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
                self.current_track = track
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
