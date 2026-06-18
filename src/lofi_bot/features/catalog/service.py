from __future__ import annotations

import logging

from lofi_bot.features.catalog.categories import CATEGORIES
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

    async def refresh_if_stale(self) -> None:
        if await self._repository.has_fresh_tracks():
            LOGGER.info("Jamendo catalog is fresh; skipping startup refresh")
            return
        await self.refresh_all_categories()

    async def refresh_all_categories(self) -> None:
        for category in CATEGORIES.values():
            tracks = await self._client.fetch_top_tracks(category, self._limit_per_category)
            if not tracks:
                LOGGER.warning(
                    "Jamendo returned no tracks for category=%s; keeping existing cache",
                    category.slug,
                )
                continue
            count = await self._repository.upsert_tracks(category.slug, tracks)
            LOGGER.info("Refreshed category=%s tracks=%s", category.slug, count)
