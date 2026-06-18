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

    async def setup_hook(self) -> None:
        self.add_view(PlayerControlView(self.guild_settings, self.player_manager))
        self.tree.add_command(
            app_commands.Command(
                name="vc",
                description="VCに接続してカテゴリ選択パネルを表示します",
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

    async def _sync_commands(self) -> None:
        if self.settings.discord_guild_id is not None:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            LOGGER.info("Synced commands to guild=%s", self.settings.discord_guild_id)
            return
        await self.tree.sync()
        LOGGER.info("Synced global commands")

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
            view=PlayerControlView(self.guild_settings, self.player_manager),
            wait=True,
        )
        await self.guild_settings.update_panel(interaction.guild.id, message.channel.id, message.id)
