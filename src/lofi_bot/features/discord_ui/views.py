from __future__ import annotations

import discord

from lofi_bot.features.catalog.categories import (
    CATEGORIES,
    DEFAULT_CATEGORY,
    build_category_source_url,
)
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository
from lofi_bot.features.playback.manager import PlayerManager

PROGRESS_BAR_SEGMENTS = 20


def format_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes}:{remaining_seconds:02d}"


def format_progress_bar(elapsed_seconds: int, duration_seconds: int) -> str:
    duration_seconds = max(0, duration_seconds)
    elapsed_seconds = max(0, elapsed_seconds)
    if duration_seconds > 0:
        elapsed_seconds = min(elapsed_seconds, duration_seconds)
        filled_segments = int((elapsed_seconds / duration_seconds) * PROGRESS_BAR_SEGMENTS)
    else:
        filled_segments = 0

    filled_segments = max(0, min(PROGRESS_BAR_SEGMENTS, filled_segments))
    empty_segments = PROGRESS_BAR_SEGMENTS - filled_segments
    bar = "#" * filled_segments + "-" * empty_segments
    return (
        f"`{bar}` "
        f"{format_duration(elapsed_seconds)} / {format_duration(duration_seconds)}"
    )


class SkipButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Skip",
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
            embed.description = "再生中ではありません。VCに入って `/vc` を使ってください。"
        await interaction.response.edit_message(embed=embed, view=self.view)


class PlayerControlView(discord.ui.View):
    def __init__(
        self,
        guild_settings: GuildSettingsRepository,
        player_manager: PlayerManager,
        default_category: str = DEFAULT_CATEGORY,
    ) -> None:
        super().__init__(timeout=None)
        self.guild_settings = guild_settings
        self.player_manager = player_manager
        self.default_category = default_category
        self.add_item(SkipButton())


async def build_panel_embed(
    guild_id: int,
    guild_settings: GuildSettingsRepository,
    player_manager: PlayerManager,
    default_category: str = DEFAULT_CATEGORY,
) -> discord.Embed:
    settings = await guild_settings.get_or_create(guild_id, default_category)
    category = CATEGORIES[DEFAULT_CATEGORY]
    track = player_manager.current_track(guild_id)

    embed = discord.Embed(
        title="BGM Bot",
        description="Chillのボーカルなし曲をランダムに再生します。",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Source",
        value=f"[Jamendo: {category.label}]({build_category_source_url(category)})",
        inline=True,
    )
    embed.add_field(
        name="Stay",
        value="ON" if settings.stay_connected else "OFF",
        inline=True,
    )

    if track is None:
        embed.add_field(name="Now Playing", value="準備中", inline=False)
    else:
        value = f"[{track.title}]({track.share_url})\nby {track.artist}"
        embed.add_field(name="Now Playing", value=value, inline=False)
        elapsed_seconds = player_manager.current_track_elapsed_seconds(guild_id) or 0
        embed.add_field(
            name="Progress",
            value=format_progress_bar(elapsed_seconds, track.duration_seconds),
            inline=False,
        )
        if track.license_url:
            embed.add_field(name="License", value=track.license_url, inline=False)

    return embed
