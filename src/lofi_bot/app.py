from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress
from types import FrameType

from lofi_bot.config import load_settings
from lofi_bot.core.database import Database
from lofi_bot.core.logging import configure_logging
from lofi_bot.features.catalog.jamendo import JamendoClient
from lofi_bot.features.catalog.repository import CatalogRepository
from lofi_bot.features.catalog.scheduler import CatalogRefreshScheduler
from lofi_bot.features.catalog.service import CatalogService
from lofi_bot.features.discord_ui.bot import LofiDiscordBot
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository
from lofi_bot.features.join_announcements.client import JoinAnnouncementClient
from lofi_bot.features.playback.manager import PlayerManager

LOGGER = logging.getLogger(__name__)
SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM)
BOT_CLOSE_TIMEOUT_SECONDS = 10.0
RemoveSignalHandlers = Callable[[], None]


async def run() -> None:
    configure_logging()
    settings = load_settings()

    database = Database(settings.database_url)
    await database.connect()
    await database.migrate()

    try:
        async with JamendoClient(settings.jamendo_client_id) as jamendo_client:
            catalog_repository = CatalogRepository(database.pool)
            guild_settings_repository = GuildSettingsRepository(database.pool)
            catalog_service = CatalogService(
                client=jamendo_client,
                repository=catalog_repository,
                limit_per_category=settings.jamendo_limit_per_category,
            )
            scheduler = CatalogRefreshScheduler(
                service=catalog_service,
                refresh_hour=settings.jamendo_refresh_hour,
                timezone_name=settings.refresh_timezone,
            )
            player_manager = PlayerManager(
                tracks=catalog_repository,
                guild_settings=guild_settings_repository,
                default_category=settings.default_category,
                catalog_service=catalog_service,
            )
            join_announcements = JoinAnnouncementClient(
                settings.join_tts_api_url,
                api_token=settings.join_tts_api_token,
            )
            bot = LofiDiscordBot(
                settings=settings,
                guild_settings=guild_settings_repository,
                player_manager=player_manager,
                scheduler=scheduler,
                join_announcements=join_announcements,
            )

            shutdown_event = asyncio.Event()
            remove_signal_handlers = _install_shutdown_signal_handlers(shutdown_event)
            await _log_join_announcement_startup_probe(join_announcements)
            bot_task = asyncio.create_task(bot.start(settings.discord_token), name="discord-bot")

            try:
                await _wait_for_bot_or_shutdown(bot_task, shutdown_event)
            finally:
                try:
                    await _shutdown_runtime(
                        scheduler,
                        player_manager,
                        join_announcements,
                        bot,
                        bot_task,
                    )
                finally:
                    remove_signal_handlers()
    finally:
        await database.close()


async def _log_join_announcement_startup_probe(
    join_announcements: JoinAnnouncementClient,
) -> None:
    if not join_announcements.is_enabled:
        LOGGER.info(
            "Join announcement startup TTS probe skipped; BGM_JOIN_TTS_API_URL is not configured"
        )
        return

    try:
        passed = await join_announcements.probe_startup_synthesis()
    except Exception:
        LOGGER.exception("Join announcement startup TTS probe failed with unexpected error")
        return

    if passed:
        LOGGER.info("Join announcement startup TTS probe passed")
    else:
        LOGGER.error("Join announcement startup TTS probe failed")


def _install_shutdown_signal_handlers(shutdown_event: asyncio.Event) -> RemoveSignalHandlers:
    loop = asyncio.get_running_loop()
    installed_loop_handlers: list[signal.Signals] = []
    previous_signal_handlers: list[tuple[signal.Signals, object]] = []

    def request_shutdown(received_signal: signal.Signals) -> None:
        if shutdown_event.is_set():
            return
        LOGGER.info("Received %s; shutting down gracefully", received_signal.name)
        shutdown_event.set()

    def request_shutdown_from_signal(signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(request_shutdown, signal.Signals(signum))

    for shutdown_signal in SHUTDOWN_SIGNALS:
        try:
            loop.add_signal_handler(shutdown_signal, request_shutdown, shutdown_signal)
        except (NotImplementedError, RuntimeError):
            try:
                previous_handler = signal.getsignal(shutdown_signal)
                signal.signal(shutdown_signal, request_shutdown_from_signal)
            except (OSError, RuntimeError, ValueError):
                LOGGER.debug(
                    "Could not install shutdown handler for %s",
                    shutdown_signal.name,
                    exc_info=True,
                )
            else:
                previous_signal_handlers.append((shutdown_signal, previous_handler))
        else:
            installed_loop_handlers.append(shutdown_signal)

    def remove_signal_handlers() -> None:
        for shutdown_signal in installed_loop_handlers:
            with suppress(RuntimeError, ValueError):
                loop.remove_signal_handler(shutdown_signal)
        for shutdown_signal, previous_handler in previous_signal_handlers:
            with suppress(OSError, RuntimeError, ValueError):
                signal.signal(shutdown_signal, previous_handler)

    return remove_signal_handlers


async def _wait_for_bot_or_shutdown(
    bot_task: asyncio.Task[None],
    shutdown_event: asyncio.Event,
) -> None:
    shutdown_task = asyncio.create_task(shutdown_event.wait(), name="shutdown-signal")
    try:
        done, _ = await asyncio.wait(
            {bot_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if bot_task in done:
            await bot_task
            return

        LOGGER.info("Shutdown requested; closing Discord bot")
    finally:
        shutdown_task.cancel()
        with suppress(asyncio.CancelledError):
            await shutdown_task


async def _close_discord_bot(
    bot: LofiDiscordBot,
    bot_task: asyncio.Task[None],
) -> None:
    if bot_task.done():
        return

    try:
        await bot.close()
    except Exception:
        bot_task.cancel()
        with suppress(asyncio.CancelledError):
            await bot_task
        raise

    try:
        await asyncio.wait_for(bot_task, timeout=BOT_CLOSE_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        if bot_task.cancelled():
            return
        raise
    except TimeoutError:
        LOGGER.warning(
            "Discord bot did not close within %.1f seconds; cancelling task",
            BOT_CLOSE_TIMEOUT_SECONDS,
        )
        bot_task.cancel()
        with suppress(asyncio.CancelledError):
            await bot_task


async def _shutdown_runtime(
    scheduler: CatalogRefreshScheduler,
    player_manager: PlayerManager,
    join_announcements: JoinAnnouncementClient,
    bot: LofiDiscordBot,
    bot_task: asyncio.Task[None],
) -> None:
    bot.begin_shutdown()
    await _run_shutdown_step("stop catalog scheduler", scheduler.stop)
    await _run_shutdown_step("close join announcements", join_announcements.close)
    await _run_shutdown_step("disconnect voice clients", player_manager.close_all)
    await _run_shutdown_step("close Discord bot", lambda: _close_discord_bot(bot, bot_task))


async def _run_shutdown_step(
    name: str,
    callback: Callable[[], Awaitable[None]],
) -> None:
    try:
        await callback()
    except Exception:
        LOGGER.exception("Failed to %s during shutdown", name)
