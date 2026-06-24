from __future__ import annotations

import discord

from lofi_bot.features.catalog.categories import (
    CATEGORIES,
    DEFAULT_CATEGORY,
    build_category_source_url,
)
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository
from lofi_bot.features.playback.manager import PlayerManager


class PauseButton(discord.ui.Button):
    def __init__(self, *, is_paused: bool) -> None:
        super().__init__(
            label="再開" if is_paused else "一時停止",
            style=discord.ButtonStyle.secondary,
            custom_id="lofi_bot:pause",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(self.view, PlayerControlView):
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        toggled = await self.view.player_manager.toggle_pause(interaction.guild.id)
        embed = await build_panel_embed(
            guild_id=interaction.guild.id,
            guild_settings=self.view.guild_settings,
            player_manager=self.view.player_manager,
            default_category=self.view.default_category,
        )
        if not toggled:
            embed.description = "再生中ではありません。VCに入って `/play` を使ってください。"
        await interaction.response.edit_message(
            embed=embed,
            view=self.view.with_current_state(interaction.guild.id),
        )


class NextTrackButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="次の曲へ",
            style=discord.ButtonStyle.secondary,
            custom_id="lofi_bot:skip",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(self.view, PlayerControlView):
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        skipped = await self.view.player_manager.skip(interaction.guild.id)
        embed = await build_panel_embed(
            guild_id=interaction.guild.id,
            guild_settings=self.view.guild_settings,
            player_manager=self.view.player_manager,
            default_category=self.view.default_category,
        )
        if not skipped:
            embed.description = "再生中ではありません。VCに入って `/play` を使ってください。"
        await interaction.response.edit_message(
            embed=embed,
            view=self.view.with_current_state(interaction.guild.id),
        )


class PlayerControlView(discord.ui.View):
    def __init__(
        self,
        guild_settings: GuildSettingsRepository,
        player_manager: PlayerManager,
        default_category: str = DEFAULT_CATEGORY,
        is_paused: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.guild_settings = guild_settings
        self.player_manager = player_manager
        self.default_category = default_category
        self.add_item(PauseButton(is_paused=is_paused))
        self.add_item(NextTrackButton())

    def with_current_state(self, guild_id: int) -> PlayerControlView:
        return PlayerControlView(
            self.guild_settings,
            self.player_manager,
            default_category=self.default_category,
            is_paused=self.player_manager.is_paused(guild_id),
        )


async def build_panel_embed(
    guild_id: int,
    guild_settings: GuildSettingsRepository,
    player_manager: PlayerManager,
    default_category: str = DEFAULT_CATEGORY,
) -> discord.Embed:
    _ = guild_settings, default_category
    category = CATEGORIES[DEFAULT_CATEGORY]
    track = player_manager.current_track(guild_id)

    embed = discord.Embed(
        title="BGMボット",
        description="チル系のボーカルなし曲をランダムに再生します。",
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="パネルが流れたら /play で再投稿できます。")
    embed.add_field(
        name="検索元",
        value=f"[Jamendo: {category.slug}]({build_category_source_url(category)})",
        inline=True,
    )

    if track is None:
        embed.add_field(name="再生中", value="準備中", inline=False)
    else:
        value = f"[{track.title}]({track.share_url})\nby {track.artist}"
        embed.add_field(name="再生中", value=value, inline=False)
        if track.license_url:
            embed.add_field(name="ライセンス", value=track.license_url, inline=False)

    return embed
