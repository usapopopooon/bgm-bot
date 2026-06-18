from __future__ import annotations

from lofi_bot.features.catalog.categories import CATEGORIES
from lofi_bot.features.catalog.service import CatalogService


class FakeJamendoClient:
    async def fetch_top_tracks(self, category, limit):  # noqa: ANN001, ANN201
        return []


class FakeCatalogRepository:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[object]]] = []

    async def has_fresh_tracks(self, max_age_hours: int = 20) -> bool:
        return False

    async def upsert_tracks(self, category_slug, tracks):  # noqa: ANN001, ANN201
        self.upserts.append((category_slug, tracks))
        return len(tracks)


async def test_refresh_all_categories_keeps_cache_when_provider_returns_no_tracks() -> None:
    repository = FakeCatalogRepository()
    service = CatalogService(
        client=FakeJamendoClient(),
        repository=repository,
        limit_per_category=200,
    )

    await service.refresh_all_categories()

    assert len(CATEGORIES) > 0
    assert repository.upserts == []
