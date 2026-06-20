from __future__ import annotations

import asyncio
import logging

from lofi_bot.features.catalog.categories import CATEGORIES, get_category
from lofi_bot.features.catalog.jamendo import JamendoClient
from lofi_bot.features.catalog.repository import CatalogRepository

LOGGER = logging.getLogger(__name__)


class CatalogService:
    def __init__(
        self,
        client: JamendoClient,
        repository: CatalogRepository,
        limit_per_category: int,
    ) -> None:
        self._client = client
        self._repository = repository
        self._limit_per_category = limit_per_category
        self._refresh_lock = asyncio.Lock()

    async def refresh_if_stale(self) -> None:
        if await self._repository.has_fresh_tracks():
            LOGGER.info("Jamendo catalog is fresh; skipping startup refresh")
            return
        await self.refresh_all_categories()

    async def refresh_all_categories(self) -> None:
        async with self._refresh_lock:
            for category in CATEGORIES.values():
                await self._refresh_category_unlocked(category.slug)

    async def refresh_category(self, category_slug: str) -> bool:
        async with self._refresh_lock:
            return await self._refresh_category_unlocked(category_slug)

    async def _refresh_category_unlocked(self, category_slug: str) -> bool:
        category = get_category(category_slug)
        tracks = await self._client.fetch_top_tracks(category, self._limit_per_category)
        if not tracks:
            LOGGER.warning(
                "Jamendo returned no tracks for category=%s; keeping existing cache",
                category.slug,
            )
            return False

        count = await self._repository.upsert_tracks(category.slug, tracks)
        LOGGER.info("Refreshed category=%s tracks=%s", category.slug, count)
        return True
