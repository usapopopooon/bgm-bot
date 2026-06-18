from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from lofi_bot.config import Settings
from lofi_bot.features.catalog.categories import get_category
from lofi_bot.features.catalog.scheduler import CatalogRefreshScheduler
from lofi_bot.features.discord_ui.views import PlayerControlView, build_panel_embed
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository
from lofi_bot.features.playback.manager import PlayerManager

LOGGER = logging.getLogger(__name__)


class LofiDiscordBot(commands.Bot):
    def __init__(
        self,
        settings: Settings,
        guild_settings: GuildSettingsRepository,
        player_manager: PlayerManager,
        scheduler: CatalogRefreshScheduler,
    ) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.guild_settings = guild_settings
        self.player_manager = player_manager
        self.scheduler = scheduler
        self.player_manager.set_track_changed_callback(self._refresh_panel_message)
        self._restored_stay_connected = False

    async def setup_hook(self) -> None:
        self.add_view(
            PlayerControlView(
                self.guild_settings,
                self.player_manager,
                default_category=self.settings.default_category,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="vc",
                description="VCに接続して操作パネルを表示します",
                callback=self._vc_command,
            )
        )
        if self.settings.sync_commands:
            await self._sync_commands()

    async def on_ready(self) -> None:
        self.scheduler.start()
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.listening, name="/vc")
        )
        LOGGER.info("Logged in as %s", self.user)
        if not self._restored_stay_connected:
            self._restored_stay_connected = True
            await self._restore_stay_connected_voice()

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        if before.channel == after.channel:
            return
        left = await self.player_manager.leave_if_alone(member.guild)
        if left:
            LOGGER.info("Left empty voice channel guild=%s", member.guild.id)

    async def _sync_commands(self) -> None:
        if self.settings.discord_guild_id is not None:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            LOGGER.info("Synced commands to guild=%s", self.settings.discord_guild_id)
            return
        await self.tree.sync()
        LOGGER.info("Synced global commands")

    async def _restore_stay_connected_voice(self) -> None:
        settings_list = await self.guild_settings.list_stay_connected()
        if not settings_list:
            return

        LOGGER.info("Restoring stay-connected voice sessions count=%s", len(settings_list))
        for settings in settings_list:
            if settings.voice_channel_id is None:
                continue

            guild = self.get_guild(settings.guild_id)
            if guild is None:
                LOGGER.warning(
                    "Cannot restore voice session; guild not found guild=%s",
                    settings.guild_id,
                )
                continue

            channel = self.get_channel(settings.voice_channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(settings.voice_channel_id)
                except discord.NotFound:
                    LOGGER.warning(
                        "Cannot restore voice session; channel not found guild=%s channel=%s",
                        settings.guild_id,
                        settings.voice_channel_id,
                    )
                    continue
                except discord.Forbidden:
                    LOGGER.warning(
                        "Cannot restore voice session; missing channel access guild=%s channel=%s",
                        settings.guild_id,
                        settings.voice_channel_id,
                    )
                    continue
                except discord.HTTPException:
                    LOGGER.exception(
                        "Cannot restore voice session; failed to fetch channel guild=%s channel=%s",
                        settings.guild_id,
                        settings.voice_channel_id,
                    )
                    continue

            if not isinstance(channel, discord.VoiceChannel):
                LOGGER.warning(
                    "Cannot restore voice session; saved channel is not a voice channel "
                    "guild=%s channel=%s",
                    settings.guild_id,
                    settings.voice_channel_id,
                )
                continue

            try:
                await self.player_manager.connect(guild, channel)
                await self.player_manager.start_saved_category(guild)
                await self._refresh_panel_message(guild.id)
                LOGGER.info(
                    "Restored stay-connected voice session guild=%s channel=%s",
                    settings.guild_id,
                    settings.voice_channel_id,
                )
            except discord.Forbidden:
                LOGGER.warning(
                    "Cannot restore voice session; missing voice permission guild=%s channel=%s",
                    settings.guild_id,
                    settings.voice_channel_id,
                )
            except discord.HTTPException:
                LOGGER.exception(
                    "Cannot restore voice session; Discord request failed guild=%s channel=%s",
                    settings.guild_id,
                    settings.voice_channel_id,
                )
            except Exception:
                LOGGER.exception(
                    "Cannot restore voice session guild=%s channel=%s",
                    settings.guild_id,
                    settings.voice_channel_id,
                )

    async def _vc_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        member = interaction.user
        if member.voice is None or member.voice.channel is None:
            await interaction.response.send_message(
                "先にVCへ入ってから `/vc` を使ってください。",
                ephemeral=True,
            )
            return
        if not isinstance(member.voice.channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "通常のボイスチャンネルで使ってください。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        settings = await self.guild_settings.get_or_create(
            interaction.guild.id,
            self.settings.default_category,
        )
        get_category(settings.selected_category)

        await self.player_manager.connect(interaction.guild, member.voice.channel)
        await self.player_manager.start_saved_category(interaction.guild)

        embed = await build_panel_embed(
            guild_id=interaction.guild.id,
            guild_settings=self.guild_settings,
            player_manager=self.player_manager,
            default_category=self.settings.default_category,
        )
        message = await interaction.followup.send(
            embed=embed,
            view=PlayerControlView(
                self.guild_settings,
                self.player_manager,
                default_category=self.settings.default_category,
            ),
            wait=True,
        )
        await self.guild_settings.update_panel(interaction.guild.id, message.channel.id, message.id)

    async def _refresh_panel_message(self, guild_id: int) -> None:
        settings = await self.guild_settings.get_or_create(
            guild_id,
            self.settings.default_category,
        )
        if settings.panel_channel_id is None or settings.panel_message_id is None:
            return

        try:
            channel = self.get_channel(settings.panel_channel_id)
            if channel is None:
                channel = await self.fetch_channel(settings.panel_channel_id)

            fetch_message = getattr(channel, "fetch_message", None)
            if fetch_message is None:
                LOGGER.warning("Panel channel cannot fetch messages guild=%s", guild_id)
                return

            message = await fetch_message(settings.panel_message_id)
            embed = await build_panel_embed(
                guild_id=guild_id,
                guild_settings=self.guild_settings,
                player_manager=self.player_manager,
                default_category=self.settings.default_category,
            )
            await message.edit(
                embed=embed,
                view=PlayerControlView(
                    self.guild_settings,
                    self.player_manager,
                    default_category=self.settings.default_category,
                ),
            )
        except discord.NotFound:
            LOGGER.warning("Panel message not found guild=%s", guild_id)
        except discord.Forbidden:
            LOGGER.warning("Missing permission to refresh panel guild=%s", guild_id)
        except discord.HTTPException:
            LOGGER.exception("Failed to refresh panel guild=%s", guild_id)
