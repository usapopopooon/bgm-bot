from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from enum import Enum

import discord
from discord import app_commands
from discord.ext import commands

from lofi_bot.config import Settings
from lofi_bot.features.catalog.categories import get_category
from lofi_bot.features.catalog.scheduler import CatalogRefreshScheduler
from lofi_bot.features.discord_ui.views import PlayerControlView, build_panel_embed
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository
from lofi_bot.features.join_announcements.client import JoinAnnouncementClient
from lofi_bot.features.playback.manager import PlayerManager

LOGGER = logging.getLogger(__name__)
SELF_VOICE_RECOVERY_INITIAL_DELAY_SECONDS = 2.0
SELF_VOICE_RECOVERY_TIMEOUT_SECONDS = 30.0
SELF_VOICE_RECOVERY_POLL_SECONDS = 1.0
READY_VOICE_RESTORE_DELAY_SECONDS = 35.0
STAY_CONNECTED_RECONNECT_ATTEMPTS = 8
STAY_CONNECTED_RECONNECT_BASE_DELAY_SECONDS = 5.0
STAY_CONNECTED_RECONNECT_MAX_DELAY_SECONDS = 300.0
GATEWAY_SERVER_ERROR_MIN_STATUS = 500
GATEWAY_SERVER_ERROR_MAX_STATUS = 599
GATEWAY_RECOVERABLE_DISCONNECT_RESTORE_WINDOW_SECONDS = 180.0
GATEWAY_SESSION_INVALIDATED_MESSAGE = "session has been invalidated"
USER_REQUESTED_DISCONNECT_WINDOW_SECONDS = 60.0
MANUAL_VOICE_DISCONNECT_AUDIT_WINDOW_SECONDS = 15.0


class VoiceDisconnectMeaning(Enum):
    USER_REQUESTED = "user_requested"
    RECOVERABLE = "recoverable"


def _stay_connected_reconnect_delay(failed_attempt: int) -> float:
    exponent = max(0, failed_attempt - 1)
    delay = STAY_CONNECTED_RECONNECT_BASE_DELAY_SECONDS * (2**exponent)
    return min(delay, STAY_CONNECTED_RECONNECT_MAX_DELAY_SECONDS)


def _is_recent_monotonic_timestamp(timestamp: float | None, window_seconds: float) -> bool:
    if timestamp is None:
        return False
    return time.monotonic() - timestamp <= window_seconds


class DiscordGatewayRecoverableDisconnectLogHandler(logging.Handler):
    def __init__(self, callback) -> None:  # noqa: ANN001
        super().__init__(level=logging.INFO)
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        if self._is_gateway_session_invalidated(record):
            self._callback()
            return

        if record.exc_info is None:
            return

        error = record.exc_info[1]
        status = getattr(error, "status", None)
        if (
            isinstance(status, int)
            and GATEWAY_SERVER_ERROR_MIN_STATUS <= status <= GATEWAY_SERVER_ERROR_MAX_STATUS
        ):
            self._callback()

    def _is_gateway_session_invalidated(self, record: logging.LogRecord) -> bool:
        return (
            record.name == "discord.gateway"
            and GATEWAY_SESSION_INVALIDATED_MESSAGE in record.getMessage()
        )


class LofiDiscordBot(commands.Bot):
    def __init__(
        self,
        settings: Settings,
        guild_settings: GuildSettingsRepository,
        player_manager: PlayerManager,
        scheduler: CatalogRefreshScheduler,
        join_announcements: JoinAnnouncementClient | None = None,
    ) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.guild_settings = guild_settings
        self.player_manager = player_manager
        self.scheduler = scheduler
        self.join_announcements = join_announcements
        self.player_manager.set_track_changed_callback(self._refresh_panel_message)
        self._restored_stay_connected = False
        self._shutting_down = False
        self._self_voice_recovery_tasks: dict[int, asyncio.Task[None]] = {}
        self._ready_voice_restore_task: asyncio.Task[None] | None = None
        self._last_gateway_recoverable_disconnect_at: float | None = None
        self._last_user_requested_disconnect_at_by_guild: dict[int, float] = {}
        self._gateway_recoverable_disconnect_log_handler = (
            DiscordGatewayRecoverableDisconnectLogHandler(
                self._record_gateway_recoverable_disconnect,
            )
        )
        self._gateway_loggers = (
            logging.getLogger("discord.client"),
            logging.getLogger("discord.gateway"),
        )
        for logger in self._gateway_loggers:
            logger.addHandler(self._gateway_recoverable_disconnect_log_handler)

    async def close(self) -> None:
        for logger in self._gateway_loggers:
            logger.removeHandler(self._gateway_recoverable_disconnect_log_handler)
        await super().close()

    async def setup_hook(self) -> None:
        self.add_view(self._build_control_view())
        self.tree.add_command(
            app_commands.Command(
                name="play",
                description="BGMの再生/停止を切り替えて操作パネルを表示します",
                callback=self._play_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="volume",
                description="音量を変更します",
                callback=self._volume_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="stay",
                description="Stayを切り替えます",
                callback=self._stay_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="leave",
                description="VCから退出します",
                callback=self._leave_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="member_commands",
                description="メンバーのコマンド利用を切り替えます（管理者のみ）",
                callback=self._member_commands_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="voice_event_sounds",
                description="入退室音を切り替えます",
                callback=self._voice_event_sounds_command,
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
            await self._restore_stay_connected_voice_with_retries()
        elif self._has_recent_gateway_recoverable_disconnect():
            self._schedule_delayed_stay_connected_restore()

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
        if after.channel == voice_client.channel and before.channel != voice_client.channel:
            await self._announce_member_join(member)
            return
        if before.channel != voice_client.channel or after.channel == voice_client.channel:
            return
        left = await self.player_manager.leave_if_alone(member.guild)
        if left:
            LOGGER.info("Left empty voice channel guild=%s", member.guild.id)

    async def _announce_member_join(self, member: discord.Member) -> None:
        join_announcements = getattr(self, "join_announcements", None)
        if join_announcements is None or not join_announcements.is_enabled:
            return
        if not self.player_manager.can_accept_announcement(member.guild.id):
            return
        settings = await self.guild_settings.get_or_create(
            member.guild.id,
            self.settings.default_category,
        )
        if not settings.voice_event_sounds_enabled:
            return
        display_name = getattr(member, "display_name", None) or getattr(member, "name", "")
        audio_data = await join_announcements.synthesize_join(member.guild.id, display_name)
        if audio_data is None:
            return
        announced = await self.player_manager.enqueue_announcement(member.guild.id, audio_data)
        if announced:
            LOGGER.info("Queued join announcement guild=%s member=%s", member.guild.id, member.id)

    def begin_shutdown(self) -> None:
        self._shutting_down = True
        for recovery_task in self._get_self_voice_recovery_tasks().values():
            recovery_task.cancel()
        ready_restore_task = getattr(self, "_ready_voice_restore_task", None)
        if ready_restore_task is not None:
            ready_restore_task.cancel()

    def _schedule_delayed_stay_connected_restore(self) -> None:
        ready_restore_task = getattr(self, "_ready_voice_restore_task", None)
        if ready_restore_task is not None and not ready_restore_task.done():
            return
        self._ready_voice_restore_task = asyncio.create_task(
            self._restore_stay_connected_voice_after_ready_delay(),
        )

    async def _restore_stay_connected_voice_after_ready_delay(self) -> None:
        try:
            await asyncio.sleep(READY_VOICE_RESTORE_DELAY_SECONDS)
            if getattr(self, "_shutting_down", False):
                return
            await self._restore_stay_connected_voice_with_retries()
        except asyncio.CancelledError:
            pass
        except Exception:
            LOGGER.exception("Failed to restore stay-connected voice after gateway reconnect")

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
        if getattr(self, "_shutting_down", False):
            LOGGER.info("Ignoring self voice disconnect during shutdown guild=%s", guild.id)
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

    def _record_gateway_recoverable_disconnect(self) -> None:
        self._last_gateway_recoverable_disconnect_at = time.monotonic()

    def _record_user_requested_disconnect(self, guild_id: int) -> None:
        disconnects_by_guild = getattr(self, "_last_user_requested_disconnect_at_by_guild", None)
        if disconnects_by_guild is None:
            disconnects_by_guild = {}
            self._last_user_requested_disconnect_at_by_guild = disconnects_by_guild
        disconnects_by_guild[guild_id] = time.monotonic()

    def _has_recent_user_requested_disconnect(self, guild_id: int) -> bool:
        disconnects_by_guild = getattr(self, "_last_user_requested_disconnect_at_by_guild", {})
        return _is_recent_monotonic_timestamp(
            disconnects_by_guild.get(guild_id),
            USER_REQUESTED_DISCONNECT_WINDOW_SECONDS,
        )

    def _has_recent_gateway_recoverable_disconnect(self) -> bool:
        return _is_recent_monotonic_timestamp(
            getattr(self, "_last_gateway_recoverable_disconnect_at", None),
            GATEWAY_RECOVERABLE_DISCONNECT_RESTORE_WINDOW_SECONDS,
        )

    async def _classify_self_voice_disconnect(self, guild: discord.Guild) -> VoiceDisconnectMeaning:
        guild_id = guild.id
        if self._has_recent_user_requested_disconnect(guild_id):
            return VoiceDisconnectMeaning.USER_REQUESTED
        if self._has_recent_gateway_recoverable_disconnect():
            return VoiceDisconnectMeaning.RECOVERABLE
        if await self._has_recent_manual_voice_disconnect_audit_entry(guild):
            return VoiceDisconnectMeaning.USER_REQUESTED
        return VoiceDisconnectMeaning.RECOVERABLE

    async def _has_recent_manual_voice_disconnect_audit_entry(
        self,
        guild: discord.Guild,
    ) -> bool:
        audit_logs = getattr(guild, "audit_logs", None)
        if audit_logs is None:
            return False

        now = datetime.now(UTC)
        try:
            async for entry in audit_logs(
                limit=5,
                action=discord.AuditLogAction.member_disconnect,
            ):
                disconnected_count = getattr(getattr(entry, "extra", None), "count", None)
                if disconnected_count != 1:
                    continue
                created_at = getattr(entry, "created_at", None)
                if created_at is None:
                    continue
                age_seconds = abs((now - created_at).total_seconds())
                if age_seconds <= MANUAL_VOICE_DISCONNECT_AUDIT_WINDOW_SECONDS:
                    return True
                if age_seconds > MANUAL_VOICE_DISCONNECT_AUDIT_WINDOW_SECONDS:
                    return False
        except discord.Forbidden:
            LOGGER.warning(
                "Cannot inspect audit log for manual voice disconnect guild=%s",
                guild.id,
            )
        except discord.HTTPException:
            LOGGER.exception(
                "Failed to inspect audit log for manual voice disconnect guild=%s",
                guild.id,
            )
        except Exception:
            LOGGER.exception(
                "Unexpected audit log failure while classifying voice disconnect guild=%s",
                guild.id,
            )

        return False

    async def _resolve_self_voice_disconnect(
        self,
        guild: discord.Guild,
        previous_channel: object,
    ) -> None:
        try:
            if getattr(self, "_shutting_down", False):
                return
            voice_client = await self._wait_for_recovered_voice_client(guild)
            if getattr(self, "_shutting_down", False):
                return
            if voice_client is not None:
                channel = getattr(voice_client, "channel", None) or previous_channel
                await self.player_manager.connect(guild, channel)
                await self.player_manager.restart_after_reconnect(guild)
                LOGGER.info(
                    "Recovered voice connection after transient disconnect guild=%s",
                    guild.id,
                )
                await self._refresh_panel_message(guild.id)
                return

            restored = await self._restore_stay_connected_after_voice_disconnect(
                guild,
                previous_channel,
            )
            if restored:
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

    async def _restore_stay_connected_after_voice_disconnect(
        self,
        guild: discord.Guild,
        previous_channel: object,
    ) -> bool:
        guild_settings = getattr(self, "guild_settings", None)
        settings = getattr(self, "settings", None)
        if guild_settings is None or settings is None:
            return False
        disconnect_meaning = await self._classify_self_voice_disconnect(guild)
        if disconnect_meaning is VoiceDisconnectMeaning.USER_REQUESTED:
            LOGGER.info(
                "Treating self voice disconnect as user-requested guild=%s",
                guild.id,
            )
            return False

        for attempt in range(1, STAY_CONNECTED_RECONNECT_ATTEMPTS + 1):
            if getattr(self, "_shutting_down", False):
                return True

            saved_settings = await guild_settings.get_or_create(guild.id, settings.default_category)
            if not saved_settings.stay_connected:
                return False

            try:
                channel = await self._resolve_stay_connected_channel(
                    saved_settings.voice_channel_id,
                    previous_channel,
                )
                if channel is None:
                    LOGGER.warning(
                        "Cannot restore stay-connected voice; channel unavailable "
                        "guild=%s channel=%s",
                        guild.id,
                        saved_settings.voice_channel_id,
                    )
                    return True

                await self.player_manager.connect(guild, channel)
                await self.player_manager.restart_after_reconnect(guild)
                LOGGER.info(
                    "Restored stay-connected voice after disconnect guild=%s channel=%s",
                    guild.id,
                    getattr(channel, "id", None),
                )
                await self._refresh_panel_message(guild.id)
                return True
            except (discord.NotFound, discord.Forbidden):
                LOGGER.warning(
                    "Cannot restore stay-connected voice; missing channel access "
                    "guild=%s channel=%s",
                    guild.id,
                    saved_settings.voice_channel_id,
                )
                return True
            except discord.HTTPException:
                LOGGER.exception(
                    "Discord request failed while restoring stay-connected voice "
                    "guild=%s attempt=%s/%s",
                    guild.id,
                    attempt,
                    STAY_CONNECTED_RECONNECT_ATTEMPTS,
                )
            except Exception:
                LOGGER.exception(
                    "Failed to restore stay-connected voice guild=%s attempt=%s/%s",
                    guild.id,
                    attempt,
                    STAY_CONNECTED_RECONNECT_ATTEMPTS,
                )

            if attempt < STAY_CONNECTED_RECONNECT_ATTEMPTS:
                delay_seconds = _stay_connected_reconnect_delay(attempt)
                LOGGER.info(
                    "Retrying stay-connected voice restore guild=%s in %.1fs attempt=%s/%s",
                    guild.id,
                    delay_seconds,
                    attempt + 1,
                    STAY_CONNECTED_RECONNECT_ATTEMPTS,
                )
                await asyncio.sleep(delay_seconds)

        LOGGER.warning("Giving up stay-connected voice restore for now guild=%s", guild.id)
        return True

    async def _resolve_stay_connected_channel(
        self,
        channel_id: int | None,
        fallback_channel: object,
    ) -> discord.VoiceChannel | None:
        channel = None
        if channel_id is not None:
            channel = self.get_channel(channel_id)
            if channel is None:
                channel = await self.fetch_channel(channel_id)

        if not isinstance(channel, discord.VoiceChannel):
            channel = fallback_channel
        if not isinstance(channel, discord.VoiceChannel):
            return None
        return channel

    async def _handle_confirmed_self_voice_disconnect(self, guild_id: int) -> None:
        if getattr(self, "_shutting_down", False):
            return

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

    async def _restore_stay_connected_voice_with_retries(self) -> None:
        completed_guild_ids: set[int] = set()
        for attempt in range(1, STAY_CONNECTED_RECONNECT_ATTEMPTS + 1):
            if getattr(self, "_shutting_down", False):
                return

            restored = await self._restore_stay_connected_voice(completed_guild_ids)
            if restored:
                return

            if attempt < STAY_CONNECTED_RECONNECT_ATTEMPTS:
                delay_seconds = _stay_connected_reconnect_delay(attempt)
                LOGGER.info(
                    "Retrying saved stay-connected restore in %.1fs attempt=%s/%s",
                    delay_seconds,
                    attempt + 1,
                    STAY_CONNECTED_RECONNECT_ATTEMPTS,
                )
                await asyncio.sleep(delay_seconds)

        LOGGER.warning("Giving up saved stay-connected restore for now")

    async def _restore_stay_connected_voice(
        self,
        completed_guild_ids: set[int] | None = None,
    ) -> bool:
        if completed_guild_ids is None:
            completed_guild_ids = set()
        settings_list = await self.guild_settings.list_stay_connected()
        if not settings_list:
            LOGGER.info("No stay-connected voice sessions to restore")
            return True

        LOGGER.info("Restoring stay-connected voice sessions count=%s", len(settings_list))
        all_restored = True
        for settings in settings_list:
            if settings.guild_id in completed_guild_ids:
                continue
            if settings.voice_channel_id is None:
                completed_guild_ids.add(settings.guild_id)
                continue

            guild = self.get_guild(settings.guild_id)
            if guild is None:
                all_restored = False
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
                    completed_guild_ids.add(settings.guild_id)
                    continue
                except discord.Forbidden:
                    LOGGER.warning(
                        "Cannot restore voice session; missing channel access guild=%s channel=%s",
                        settings.guild_id,
                        settings.voice_channel_id,
                    )
                    completed_guild_ids.add(settings.guild_id)
                    continue
                except discord.HTTPException:
                    LOGGER.exception(
                        "Cannot restore voice session; failed to fetch channel guild=%s channel=%s",
                        settings.guild_id,
                        settings.voice_channel_id,
                    )
                    all_restored = False
                    continue

            if not isinstance(channel, discord.VoiceChannel):
                LOGGER.warning(
                    "Cannot restore voice session; saved channel is not a voice channel "
                    "guild=%s channel=%s",
                    settings.guild_id,
                    settings.voice_channel_id,
                )
                completed_guild_ids.add(settings.guild_id)
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
                completed_guild_ids.add(settings.guild_id)
            except discord.Forbidden:
                LOGGER.warning(
                    "Cannot restore voice session; missing voice permission guild=%s channel=%s",
                    settings.guild_id,
                    settings.voice_channel_id,
                )
                completed_guild_ids.add(settings.guild_id)
            except discord.HTTPException:
                LOGGER.exception(
                    "Cannot restore voice session; Discord request failed guild=%s channel=%s",
                    settings.guild_id,
                    settings.voice_channel_id,
                )
                all_restored = False
            except Exception:
                LOGGER.exception(
                    "Cannot restore voice session guild=%s channel=%s",
                    settings.guild_id,
                    settings.voice_channel_id,
                )
                all_restored = False

        return all_restored

    async def _reject_non_admin(self, interaction: discord.Interaction, message: str) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return True

        if not interaction.permissions.administrator:
            await interaction.response.send_message(message, ephemeral=True)
            return True

        return False

    async def _reject_unauthorized_command_user(
        self,
        interaction: discord.Interaction,
        message: str,
    ) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return True

        if interaction.permissions.administrator:
            return False

        settings = await self.guild_settings.get_or_create(
            interaction.guild.id,
            self.settings.default_category,
        )
        if settings.member_commands_enabled:
            return False

        await interaction.response.send_message(message, ephemeral=True)
        return True

    async def _play_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        if await self._reject_unauthorized_command_user(
            interaction,
            "BGM再生は現在管理者のみ使えます。",
        ):
            return

        voice_client = interaction.guild.voice_client
        if voice_client is not None and voice_client.is_connected():
            self._record_user_requested_disconnect(interaction.guild.id)
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
                "先にVCへ入ってから `/play` を使ってください。",
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
        settings = await self.guild_settings.get_or_create(
            interaction.guild.id,
            self.settings.default_category,
        )
        message = await interaction.followup.send(
            embed=embed,
            view=self._build_control_view(
                interaction.guild.id,
                voice_event_sounds_enabled=settings.voice_event_sounds_enabled,
            ),
            wait=True,
        )
        await self.guild_settings.update_panel(interaction.guild.id, message.channel.id, message.id)

    def _build_control_view(
        self,
        guild_id: int | None = None,
        *,
        voice_event_sounds_enabled: bool | None = None,
    ) -> PlayerControlView:
        return PlayerControlView(
            self.guild_settings,
            self.player_manager,
            default_category=self.settings.default_category,
            is_paused=(guild_id is not None and self.player_manager.is_paused(guild_id)),
            voice_event_sounds_enabled=voice_event_sounds_enabled,
        )

    @app_commands.describe(percent="1〜100の音量")
    async def _volume_command(
        self,
        interaction: discord.Interaction,
        percent: app_commands.Range[int, 1, 100],
    ) -> None:
        if await self._reject_unauthorized_command_user(
            interaction,
            "音量変更は現在管理者のみ使えます。",
        ):
            return

        is_playing = await self.player_manager.set_volume(interaction.guild.id, percent / 100)
        message = f"音量を {percent}% にしました。"
        if not is_playing:
            message += " 再生中ではないので、次回 `/play` から反映します。"

        await interaction.response.send_message(message, ephemeral=True)
        await self._refresh_panel_message(interaction.guild.id)

    async def _stay_command(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if await self._reject_unauthorized_command_user(
            interaction,
            "Stay変更は現在管理者のみ使えます。",
        ):
            return

        enabled = not await self.player_manager.get_stay_connected(interaction.guild.id)
        await self.player_manager.set_stay_connected(interaction.guild.id, enabled)
        left = False
        if not enabled:
            self._record_user_requested_disconnect(interaction.guild.id)
            left = await self.player_manager.leave_if_alone(interaction.guild)

        message = f"Stayを {'ON' if enabled else 'OFF'} にしました。"
        if left:
            message += " VCが空だったため退出しました。"

        await interaction.response.send_message(message, ephemeral=True)
        await self._refresh_panel_message(interaction.guild.id)

    async def _leave_command(self, interaction: discord.Interaction) -> None:
        if await self._reject_unauthorized_command_user(
            interaction,
            "VC退出は現在管理者のみ使えます。",
        ):
            return

        self._record_user_requested_disconnect(interaction.guild.id)
        left = await self.player_manager.leave(
            interaction.guild.id,
            clear_saved_channel=True,
            disable_stay_connected=True,
        )
        message = "VCから退出しました。" if left else "接続中ではありません。"

        await interaction.response.send_message(message, ephemeral=True)
        await self._refresh_panel_message(interaction.guild.id)

    @app_commands.default_permissions(administrator=True)
    async def _member_commands_command(self, interaction: discord.Interaction) -> None:
        if await self._reject_non_admin(
            interaction,
            "メンバーのコマンド利用を変更できるのは管理者だけです。",
        ):
            return

        settings = await self.guild_settings.get_or_create(
            interaction.guild.id,
            self.settings.default_category,
        )
        enabled = not settings.member_commands_enabled
        await self.guild_settings.update_member_commands_enabled(interaction.guild.id, enabled)

        message = f"メンバーのコマンド利用を {'ON' if enabled else 'OFF'} にしました。"
        await interaction.response.send_message(message, ephemeral=True)

    async def _voice_event_sounds_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内で使ってください。", ephemeral=True)
            return

        settings = await self.guild_settings.get_or_create(
            interaction.guild.id,
            self.settings.default_category,
        )
        enabled = not settings.voice_event_sounds_enabled
        await self.guild_settings.update_voice_event_sounds_enabled(interaction.guild.id, enabled)

        message = f"入退室音を {'ON' if enabled else 'OFF'} にしました。"
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
                view=self._build_control_view(
                    guild_id,
                    voice_event_sounds_enabled=settings.voice_event_sounds_enabled,
                ),
            )
        except discord.NotFound:
            LOGGER.warning("Panel message not found guild=%s", guild_id)
        except discord.Forbidden:
            LOGGER.warning("Missing permission to refresh panel guild=%s", guild_id)
        except discord.HTTPException:
            LOGGER.exception("Failed to refresh panel guild=%s", guild_id)
