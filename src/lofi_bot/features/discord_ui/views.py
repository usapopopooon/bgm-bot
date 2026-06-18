from __future__ import annotations

import discord

from lofi_bot.features.catalog.categories import CATEGORIES
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository
from lofi_bot.features.playback.manager import PlayerManager


class CategorySelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label=category.label,
                value=category.slug,
                description=category.description[:100],
            )
            for category in CATEGORIES.values()
        ]
        super().__init__(
            placeholder="ランキングカテゴリを選択",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="lofi_bot:category_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(self.view, PlayerControlView):
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        category_slug = self.values[0]
        is_playing = await self.view.player_manager.set_category(
            interaction.guild.id,
            category_slug,
        )
        embed = await build_panel_embed(
            guild_id=interaction.guild.id,
            guild_settings=self.view.guild_settings,
            player_manager=self.view.player_manager,
        )
        if not is_playing:
            embed.description = (
                "カテゴリを保存しました。再生するにはVCに入って `/vc` を使ってください。"
            )
        await interaction.response.edit_message(embed=embed, view=self.view)


class SkipButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Skip",
            style=discord.ButtonStyle.secondary,
            custom_id="lofi_bot:skip",
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
        )
        if not skipped:
            embed.description = "再生中ではありません。VCに入って `/vc` を使ってください。"
        await interaction.response.edit_message(embed=embed, view=self.view)


class LeaveButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Leave",
            style=discord.ButtonStyle.danger,
            custom_id="lofi_bot:leave",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(self.view, PlayerControlView):
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        await self.view.player_manager.leave(interaction.guild.id)
        embed = await build_panel_embed(
            guild_id=interaction.guild.id,
            guild_settings=self.view.guild_settings,
            player_manager=self.view.player_manager,
        )
        embed.description = "VCから退出しました。"
        await interaction.response.edit_message(embed=embed, view=self.view)


class PlayerControlView(discord.ui.View):
    def __init__(
        self,
        guild_settings: GuildSettingsRepository,
        player_manager: PlayerManager,
    ) -> None:
        super().__init__(timeout=None)
        self.guild_settings = guild_settings
        self.player_manager = player_manager
        self.add_item(CategorySelect())
        self.add_item(SkipButton())
        self.add_item(LeaveButton())


async def build_panel_embed(
    guild_id: int,
    guild_settings: GuildSettingsRepository,
    player_manager: PlayerManager,
    default_category: str = "lofi",
) -> discord.Embed:
    settings = await guild_settings.get_or_create(guild_id, default_category)
    category = CATEGORIES[settings.selected_category]
    track = player_manager.current_track(guild_id)

    embed = discord.Embed(
        title="Lofi Bot",
        description="ランキングカテゴリを選ぶと、その上位曲からランダムに再生します。",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Category", value=category.label, inline=True)

    if track is None:
        embed.add_field(name="Now Playing", value="準備中", inline=False)
    else:
        value = f"[{track.title}]({track.share_url})\nby {track.artist}"
        embed.add_field(name="Now Playing", value=value, inline=False)
        if track.license_url:
            embed.add_field(name="License", value=track.license_url, inline=False)

    return embed
