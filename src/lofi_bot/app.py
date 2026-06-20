from __future__ import annotations

from lofi_bot.config import load_settings
from lofi_bot.core.database import Database
from lofi_bot.core.logging import configure_logging
from lofi_bot.features.catalog.jamendo import JamendoClient
from lofi_bot.features.catalog.repository import CatalogRepository
from lofi_bot.features.catalog.scheduler import CatalogRefreshScheduler
from lofi_bot.features.catalog.service import CatalogService
from lofi_bot.features.discord_ui.bot import LofiDiscordBot
from lofi_bot.features.guild_settings.repository import GuildSettingsRepository
from lofi_bot.features.playback.manager import PlayerManager


async def run() -> None:
    configure_logging()
    settings = load_settings()

    database = Database(settings.database_url)
    await database.connect()
    await database.migrate()

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
        bot = LofiDiscordBot(
            settings=settings,
            guild_settings=guild_settings_repository,
            player_manager=player_manager,
            scheduler=scheduler,
        )

        try:
            await bot.start(settings.discord_token)
        finally:
            await scheduler.stop()
            await player_manager.close_all()
            await bot.close()
            await database.close()
