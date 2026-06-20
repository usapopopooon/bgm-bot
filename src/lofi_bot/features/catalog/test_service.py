from __future__ import annotations

from lofi_bot.features.catalog.categories import CATEGORIES
from lofi_bot.features.catalog.models import Track
from lofi_bot.features.catalog.service import CatalogService


class FakeJamendoClient:
    def __init__(self, tracks: list[Track] | None = None) -> None:
        self.tracks = tracks or []
        self.fetches: list[tuple[str, int]] = []

    async def fetch_top_tracks(self, category, limit):  # noqa: ANN001, ANN201
        self.fetches.append((category.slug, limit))
        return self.tracks


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


async def test_refresh_category_upserts_provider_tracks() -> None:
    track = Track(
        provider_track_id="jamendo-1",
        title="Night Study",
        artist="Cafe Artist",
        audio_url="https://example.com/audio.mp3",
        share_url="https://example.com/track",
        license_url=None,
        duration_seconds=120,
        ranking_category="chill",
        rank_position=1,
    )
    client = FakeJamendoClient([track])
    repository = FakeCatalogRepository()
    service = CatalogService(
        client=client,
        repository=repository,
        limit_per_category=200,
    )

    refreshed = await service.refresh_category("chill")

    assert refreshed is True
    assert client.fetches == [("chill", 200)]
    assert repository.upserts == [("chill", [track])]


async def test_refresh_category_returns_false_when_provider_returns_no_tracks() -> None:
    client = FakeJamendoClient()
    repository = FakeCatalogRepository()
    service = CatalogService(
        client=client,
        repository=repository,
        limit_per_category=200,
    )

    refreshed = await service.refresh_category("chill")

    assert refreshed is False
    assert repository.upserts == []
