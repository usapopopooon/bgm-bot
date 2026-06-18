from __future__ import annotations

from lofi_bot.features.catalog.repository import CatalogRepository


class FakePool:
    def __init__(self) -> None:
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        if "category_count" in query:
            return {"category_count": 0}
        return None


async def test_has_fresh_tracks_only_counts_instrumental_cache() -> None:
    pool = FakePool()
    repository = CatalogRepository(pool)

    result = await repository.has_fresh_tracks()

    assert result is False
    query, args = pool.fetchrow_calls[0]
    assert "instrumental_only = TRUE" in query
    assert args == (20,)


async def test_get_random_track_only_selects_instrumental_cache() -> None:
    pool = FakePool()
    repository = CatalogRepository(pool)

    result = await repository.get_random_track(guild_id=123, category_slug="chill")

    assert result is None
    assert len(pool.fetchrow_calls) == 2
    for query, _args in pool.fetchrow_calls:
        assert "instrumental_only = TRUE" in query
