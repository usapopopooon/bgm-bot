from __future__ import annotations

import logging

import discord

from lofi_bot.features.catalog.categories import CATEGORIES, build_category_source_url
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository
from lofi_bot.features.playback.manager import PlayerManager

LOGGER = logging.getLogger(__name__)


def format_volume(volume: float) -> str:
    return f"{round(volume * 100)}%"


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
            placeholder="カテゴリを選択",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="lofi_bot:category_select",
            row=0,
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
            default_category=self.view.default_category,
        )
        if not is_playing:
            embed.description = (
                "カテゴリを保存しました。再生するにはVCに入って `/vc` を使ってください。"
            )
        await interaction.response.edit_message(embed=embed, view=self.view)


class VolumeModal(discord.ui.Modal):
    def __init__(
        self,
        guild_id: int,
        guild_settings: GuildSettingsRepository,
        player_manager: PlayerManager,
        default_percent: int,
        default_category: str,
    ) -> None:
        super().__init__(title="音量設定")
        self.guild_id = guild_id
        self.guild_settings = guild_settings
        self.player_manager = player_manager
        self.default_category = default_category
        self.percent = discord.ui.TextInput(
            label="音量",
            placeholder="1〜100",
            default=str(default_percent),
            min_length=1,
            max_length=3,
        )
        self.add_item(self.percent)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_value = str(self.percent.value).strip().removesuffix("%")
        try:
            percent = int(raw_value)
        except ValueError:
            await interaction.response.send_message(
                "音量は1〜100の数字で入力してください。",
                ephemeral=True,
            )
            return

        if percent < 1 or percent > 100:
            await interaction.response.send_message(
                "音量は1〜100の範囲で入力してください。",
                ephemeral=True,
            )
            return

        is_playing = await self.player_manager.set_volume(self.guild_id, percent / 100)
        message = f"音量を {percent}% にしました。"
        if not is_playing:
            message += " 再生中ではないので、次回 `/vc` から反映します。"

        await interaction.response.send_message(message, ephemeral=True)

        if interaction.message is not None:
            embed = await build_panel_embed(
                guild_id=self.guild_id,
                guild_settings=self.guild_settings,
                player_manager=self.player_manager,
                default_category=self.default_category,
            )
            try:
                await interaction.message.edit(
                    embed=embed,
                    view=PlayerControlView(
                        self.guild_settings,
                        self.player_manager,
                        default_category=self.default_category,
                    ),
                )
            except discord.HTTPException:
                LOGGER.warning("Failed to refresh volume panel guild=%s", self.guild_id)


class VolumeButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Volume",
            style=discord.ButtonStyle.secondary,
            custom_id="lofi_bot:volume",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(self.view, PlayerControlView):
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        settings = await self.view.guild_settings.get_or_create(
            interaction.guild.id,
            self.view.default_category,
        )
        await interaction.response.send_modal(
            VolumeModal(
                guild_id=interaction.guild.id,
                guild_settings=self.view.guild_settings,
                player_manager=self.view.player_manager,
                default_percent=round(settings.volume * 100),
                default_category=self.view.default_category,
            )
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


class StayButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="常駐",
            style=discord.ButtonStyle.secondary,
            custom_id="lofi_bot:stay",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(self.view, PlayerControlView):
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        settings = await self.view.guild_settings.get_or_create(
            interaction.guild.id,
            self.view.default_category,
        )
        stay_connected = not settings.stay_connected
        await self.view.player_manager.set_stay_connected(interaction.guild.id, stay_connected)
        left = False
        if not stay_connected:
            left = await self.view.player_manager.leave_if_alone(interaction.guild)

        embed = await build_panel_embed(
            guild_id=interaction.guild.id,
            guild_settings=self.view.guild_settings,
            player_manager=self.view.player_manager,
            default_category=self.view.default_category,
        )
        embed.description = f"常駐を{'ON' if stay_connected else 'OFF'}にしました。"
        if left:
            embed.description += " VCに誰もいないため退出しました。"
        await interaction.response.edit_message(embed=embed, view=self.view)


class LeaveButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Leave",
            style=discord.ButtonStyle.danger,
            custom_id="lofi_bot:leave",
            row=1,
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
            default_category=self.view.default_category,
        )
        embed.description = "VCから退出しました。"
        await interaction.response.edit_message(embed=embed, view=self.view)


class PlayerControlView(discord.ui.View):
    def __init__(
        self,
        guild_settings: GuildSettingsRepository,
        player_manager: PlayerManager,
        default_category: str = "lofi",
    ) -> None:
        super().__init__(timeout=None)
        self.guild_settings = guild_settings
        self.player_manager = player_manager
        self.default_category = default_category
        self.add_item(CategorySelect())
        self.add_item(VolumeButton())
        self.add_item(SkipButton())
        self.add_item(StayButton())
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
        title="BGM Bot",
        description="カテゴリを選ぶと、その雰囲気に合う曲をランダムに再生します。",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Category", value=category.label, inline=True)
    embed.add_field(
        name="Source",
        value=f"[Jamendo: {category.label}]({build_category_source_url(category)})",
        inline=True,
    )
    embed.add_field(name="Volume", value=format_volume(settings.volume), inline=True)
    embed.add_field(
        name="常駐",
        value="ON" if settings.stay_connected else "OFF",
        inline=True,
    )

    if track is None:
        embed.add_field(name="Now Playing", value="準備中", inline=False)
    else:
        value = f"[{track.title}]({track.share_url})\nby {track.artist}"
        embed.add_field(name="Now Playing", value=value, inline=False)
        if track.license_url:
            embed.add_field(name="License", value=track.license_url, inline=False)

    return embed
