from __future__ import annotations

import asyncio
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
SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS = 2.0
SELF_VOICE_RECOVERY_TIMEOUT_SECONDS = 30.0
SELF_VOICE_RECOVERY_POLL_SECONDS = 1.0


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
        self._self_voice_recovery_tasks: dict[int, asyncio.Task[None]] = {}

    async def setup_hook(self) -> None:
        self.add_view(self._build_control_view())
        self.tree.add_command(
            app_commands.Command(
                name="vc",
                description="VCへの接続/切断を切り替えて操作パネルを表示します（管理者のみ）",
                callback=self._vc_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="volume",
                description="音量を変更します（管理者のみ）",
                callback=self._volume_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="stay",
                description="Stayを切り替えます（管理者のみ）",
                callback=self._stay_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="leave",
                description="VCから退出します（管理者のみ）",
                callback=self._leave_command,
            )
        )
        if self.settings.sync_commands:
            await self._sync_commands()

    async def on_ready(self) -> None:
        self.scheduler.start()
        await self.change_presence(activity=discord.CustomActivity(name="BGMを流しています"))
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
        if before.channel == after.channel:
            return
        if self._is_self_voice_member(member):
            await self._handle_self_voice_disconnect(member.guild, before, after)
            return
        if member.bot:
            return
        voice_client = member.guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            return
        if before.channel != voice_client.channel or after.channel == voice_client.channel:
            return
        left = await self.player_manager.leave_if_alone(member.guild)
        if left:
            LOGGER.info("Left empty voice channel guild=%s", member.guild.id)

    def _is_self_voice_member(self, member: discord.Member) -> bool:
        bot_user = getattr(getattr(self, "_connection", None), "user", None)
        bot_user_id = getattr(bot_user, "id", None)
        return bot_user_id is not None and getattr(member, "id", None) == bot_user_id

    async def _handle_self_voice_disconnect(
        self,
        guild: discord.Guild,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel is None or after.channel is not None:
            return

        recovery_tasks = self._get_self_voice_recovery_tasks()
        recovery_task = recovery_tasks.get(guild.id)
        if recovery_task is not None and not recovery_task.done():
            return

        recovery_tasks[guild.id] = asyncio.create_task(
            self._resolve_self_voice_disconnect(guild, before.channel),
        )

    def _get_self_voice_recovery_tasks(self) -> dict[int, asyncio.Task[None]]:
        recovery_tasks = getattr(self, "_self_voice_recovery_tasks", None)
        if recovery_tasks is None:
            recovery_tasks = {}
            self._self_voice_recovery_tasks = recovery_tasks
        return recovery_tasks

    async def _resolve_self_voice_disconnect(
        self,
        guild: discord.Guild,
        previous_channel: object,
    ) -> None:
        try:
            voice_client = await self._wait_for_recovered_voice_client(guild)
            if voice_client is not None:
                channel = getattr(voice_client, "channel", None) or previous_channel
                await self.player_manager.connect(guild, channel)
                await self.player_manager.start_saved_category(guild)
                LOGGER.info(
                    "Recovered voice connection after transient disconnect guild=%s",
                    guild.id,
                )
                await self._refresh_panel_message(guild.id)
                return

            await self._handle_confirmed_self_voice_disconnect(guild.id)
        except Exception:
            LOGGER.exception("Failed to resolve self voice disconnect guild=%s", guild.id)
        finally:
            recovery_tasks = self._get_self_voice_recovery_tasks()
            if recovery_tasks.get(guild.id) is asyncio.current_task():
                recovery_tasks.pop(guild.id, None)

    async def _wait_for_recovered_voice_client(
        self,
        guild: discord.Guild,
    ) -> discord.VoiceClient | None:
        timeout = max(0.0, SELF_VOICE_RECOVERY_TIMEOUT_SECONDS)
        initial_delay = min(SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS, timeout)
        deadline = asyncio.get_running_loop().time() + timeout

        if initial_delay > 0:
            await asyncio.sleep(initial_delay)

        while True:
            voice_client = guild.voice_client
            if voice_client is None:
                return None
            if voice_client.is_connected():
                return voice_client

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(SELF_VOICE_RECOVERY_POLL_SECONDS, remaining))

    async def _handle_confirmed_self_voice_disconnect(self, guild_id: int) -> None:
        disconnected = await self.player_manager.handle_external_disconnect(guild_id)
        if not disconnected:
            return

        LOGGER.info("Bot was disconnected manually guild=%s", guild_id)
        await self._refresh_panel_message(guild_id)

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

    async def _reject_non_admin(self, interaction: discord.Interaction, message: str) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return True

        if not interaction.permissions.administrator:
            await interaction.response.send_message(message, ephemeral=True)
            return True

        return False

    @app_commands.default_permissions(administrator=True)
    async def _vc_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        if await self._reject_non_admin(
            interaction,
            "VC接続できるのは管理者だけです。",
        ):
            return

        voice_client = interaction.guild.voice_client
        if voice_client is not None and voice_client.is_connected():
            left = await self.player_manager.leave(
                interaction.guild.id,
                clear_saved_channel=True,
                disable_stay_connected=True,
            )
            if not left and voice_client.is_connected():
                await voice_client.disconnect(force=True)
                left = True
            message = "VCから退出しました。" if left else "接続中ではありません。"
            await interaction.response.send_message(message, ephemeral=True)
            await self._refresh_panel_message(interaction.guild.id)
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

        await self._send_panel(interaction)

    async def _send_panel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            raise RuntimeError("Panel can only be sent in a guild")

        embed = await build_panel_embed(
            guild_id=interaction.guild.id,
            guild_settings=self.guild_settings,
            player_manager=self.player_manager,
            default_category=self.settings.default_category,
        )
        message = await interaction.followup.send(
            embed=embed,
            view=self._build_control_view(interaction.guild.id),
            wait=True,
        )
        await self.guild_settings.update_panel(interaction.guild.id, message.channel.id, message.id)

    def _build_control_view(self, guild_id: int | None = None) -> PlayerControlView:
        return PlayerControlView(
            self.guild_settings,
            self.player_manager,
            default_category=self.settings.default_category,
            is_paused=(
                guild_id is not None and self.player_manager.is_paused(guild_id)
            ),
        )

    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(percent="1〜100の音量")
    async def _volume_command(
        self,
        interaction: discord.Interaction,
        percent: app_commands.Range[int, 1, 100],
    ) -> None:
        if await self._reject_non_admin(
            interaction,
            "音量を変更できるのは管理者だけです。",
        ):
            return

        is_playing = await self.player_manager.set_volume(interaction.guild.id, percent / 100)
        message = f"音量を {percent}% にしました。"
        if not is_playing:
            message += " 再生中ではないので、次回 `/vc` から反映します。"

        await interaction.response.send_message(message, ephemeral=True)
        await self._refresh_panel_message(interaction.guild.id)

    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(enabled="StayをONにするならtrue、OFFにするならfalse")
    async def _stay_command(
        self,
        interaction: discord.Interaction,
        enabled: bool,
    ) -> None:
        if await self._reject_non_admin(
            interaction,
            "Stayを変更できるのは管理者だけです。",
        ):
            return

        await self.player_manager.set_stay_connected(interaction.guild.id, enabled)
        left = False
        if not enabled:
            left = await self.player_manager.leave_if_alone(interaction.guild)

        message = f"Stayを {'ON' if enabled else 'OFF'} にしました。"
        if left:
            message += " VCが空だったため退出しました。"

        await interaction.response.send_message(message, ephemeral=True)
        await self._refresh_panel_message(interaction.guild.id)

    @app_commands.default_permissions(administrator=True)
    async def _leave_command(self, interaction: discord.Interaction) -> None:
        if await self._reject_non_admin(
            interaction,
            "VCから退出できるのは管理者だけです。",
        ):
            return

        left = await self.player_manager.leave(
            interaction.guild.id,
            clear_saved_channel=True,
            disable_stay_connected=True,
        )
        message = "VCから退出しました。" if left else "接続中ではありません。"

        await interaction.response.send_message(message, ephemeral=True)
        await self._refresh_panel_message(interaction.guild.id)

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
                view=self._build_control_view(guild_id),
            )
        except discord.NotFound:
            LOGGER.warning("Panel message not found guild=%s", guild_id)
        except discord.Forbidden:
            LOGGER.warning("Missing permission to refresh panel guild=%s", guild_id)
        except discord.HTTPException:
            LOGGER.exception("Failed to refresh panel guild=%s", guild_id)
