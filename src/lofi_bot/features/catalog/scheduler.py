from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from lofi_bot.features.catalog.service import CatalogService

LOGGER = logging.getLogger(__name__)


class CatalogRefreshScheduler:
    def __init__(self, service: CatalogService, refresh_hour: int, timezone_name: str) -> None:
        self._service = service
        self._refresh_hour = refresh_hour
        self._timezone = ZoneInfo(timezone_name)
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="jamendo-catalog-refresh")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        await self._safe_refresh_if_stale()
        while True:
            await asyncio.sleep(self._seconds_until_next_refresh())
            await self._safe_refresh_all_categories()

    async def _safe_refresh_if_stale(self) -> None:
        try:
            await self._service.refresh_if_stale()
        except Exception:
            LOGGER.exception("Jamendo startup refresh failed")

    async def _safe_refresh_all_categories(self) -> None:
        try:
            await self._service.refresh_all_categories()
        except Exception:
            LOGGER.exception("Jamendo scheduled refresh failed")

    def _seconds_until_next_refresh(self) -> float:
        now = datetime.now(self._timezone)
        target = now.replace(hour=self._refresh_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()
