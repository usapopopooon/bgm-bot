from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import discord

from lofi_bot.features.catalog.categories import get_category
from lofi_bot.features.catalog.models import Track
from lofi_bot.features.catalog.repository import CatalogRepository
from lofi_bot.features.catalog.service import CatalogService
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository
from lofi_bot.features.playback.player import GuildPlayer, clamp_volume

LOGGER = logging.getLogger(__name__)
TrackChangedCallback = Callable[[int], Awaitable[None]]
VOICE_CONNECT_TIMEOUT_SECONDS = 20


class PlayerManager:
    def __init__(
        self,
        tracks: CatalogRepository,
        guild_settings: GuildSettingsRepository,
        default_category: str,
        catalog_service: CatalogService | None = None,
    ) -> None:
        self._tracks = tracks
        self._guild_settings = guild_settings
        self._default_category = default_category
        self._catalog_service = catalog_service
        self._players: dict[int, GuildPlayer] = {}
        self._track_changed_callback: TrackChangedCallback | None = None

    def set_track_changed_callback(self, callback: TrackChangedCallback | None) -> None:
        self._track_changed_callback = callback
        for player in self._players.values():
            player.set_track_changed_callback(callback)

    async def connect(self, guild: discord.Guild, channel: discord.VoiceChannel) -> GuildPlayer:
        settings = await self._guild_settings.get_or_create(guild.id, self._default_category)
        if settings.voice_channel_id != channel.id:
            await self._guild_settings.update_voice_channel(guild.id, channel.id)

        voice_client = guild.voice_client
        if voice_client is not None and voice_client.is_connected():
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
            await self._ensure_speaker_muted(guild, channel)
        else:
            voice_client = await channel.connect(
                reconnect=True,
                timeout=VOICE_CONNECT_TIMEOUT_SECONDS,
                self_deaf=True,
            )

        player = self._players.get(guild.id)
        if player is None:
            player = GuildPlayer(
                guild_id=guild.id,
                voice_client=voice_client,
                tracks=self._tracks,
                guild_settings=self._guild_settings,
                category_slug=settings.selected_category,
                volume=settings.volume,
                on_track_changed=self._track_changed_callback,
                refresh_catalog=self._refresh_catalog_category,
            )
            self._players[guild.id] = player
        else:
            player.voice_client = voice_client
            player.set_volume(settings.volume)
            player.set_track_changed_callback(self._track_changed_callback)

        return player

    async def _refresh_catalog_category(self, category_slug: str) -> bool:
        if self._catalog_service is None:
            return False
        return await self._catalog_service.refresh_category(category_slug)

    async def _ensure_speaker_muted(
        self,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
    ) -> None:
        change_voice_state = getattr(guild, "change_voice_state", None)
        if change_voice_state is None:
            return
        await change_voice_state(channel=channel, self_deaf=True, self_mute=False)

    async def start_saved_category(self, guild: discord.Guild) -> None:
        player = self._players.get(guild.id)
        if player is None:
            return
        await player.play_next()

    async def set_category(self, guild_id: int, category_slug: str) -> bool:
        get_category(category_slug)
        player = self._players.get(guild_id)
        await self._guild_settings.update_selected_category(guild_id, category_slug)
        if player is None or not player.is_active:
            return False
        await player.set_category(category_slug)
        return True

    async def skip(self, guild_id: int) -> bool:
        player = self._players.get(guild_id)
        if player is None or not player.is_active:
            return False
        await player.skip()
        return True

    async def toggle_pause(self, guild_id: int) -> bool:
        player = self._players.get(guild_id)
        if player is None or not player.is_active:
            return False
        return await player.toggle_pause()

    async def set_volume(self, guild_id: int, volume: float) -> bool:
        volume = clamp_volume(volume)
        await self._guild_settings.update_volume(guild_id, volume)
        player = self._players.get(guild_id)
        if player is None or not player.is_active:
            return False
        player.set_volume(volume)
        return True

    async def set_stay_connected(self, guild_id: int, stay_connected: bool) -> None:
        await self._guild_settings.update_stay_connected(guild_id, stay_connected)

    async def leave(
        self,
        guild_id: int,
        *,
        clear_saved_channel: bool = False,
        disable_stay_connected: bool = False,
    ) -> bool:
        player = self._players.pop(guild_id, None)
        if clear_saved_channel:
            await self._guild_settings.clear_voice_channel(guild_id)
        if disable_stay_connected:
            await self._guild_settings.update_stay_connected(guild_id, False)
        if player is None:
            return False
        await player.stop()
        return True

    async def handle_external_disconnect(self, guild_id: int) -> bool:
        player = self._players.pop(guild_id, None)
        if player is None:
            return False

        await self._guild_settings.clear_voice_channel(guild_id)
        await self._guild_settings.update_stay_connected(guild_id, False)
        await player.stop()
        return True

    async def leave_if_alone(self, guild: discord.Guild) -> bool:
        voice_client = guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            return False

        settings = await self._guild_settings.get_or_create(guild.id, self._default_category)
        if settings.stay_connected:
            return False

        channel = voice_client.channel
        members = getattr(channel, "members", ())
        if any(not member.bot for member in members):
            return False

        left = await self.leave(guild.id, clear_saved_channel=True)
        if left and self._track_changed_callback is not None:
            await self._track_changed_callback(guild.id)
        return left

    async def close_all(self) -> None:
        for guild_id in list(self._players):
            await self.leave(guild_id)

    def current_track(self, guild_id: int) -> Track | None:
        player = self._players.get(guild_id)
        return player.current_track if player is not None else None

    def is_paused(self, guild_id: int) -> bool:
        player = self._players.get(guild_id)
        return player.is_paused if player is not None else False
