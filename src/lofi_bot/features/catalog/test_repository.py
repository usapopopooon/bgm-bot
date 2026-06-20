from __future__ import annotations

from lofi_bot.features.catalog.repository import CatalogRepository


class FakePool:
    def __init__(self, *, fetchrow_results: list[dict[str, object] | None] | None = None) -> None:
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrow_results = fetchrow_results or []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        if "category_count" in query:
            return {"category_count": 0}
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None


def make_track_row(track_id: int) -> dict[str, object]:
    return {
        "id": track_id,
        "provider_track_id": f"jamendo-{track_id}",
        "title": "Night Study",
        "artist": "Cafe Artist",
        "audio_url": "https://example.com/audio.mp3",
        "share_url": "https://example.com/track",
        "license_url": None,
        "duration_seconds": 120,
        "ranking_category": "chill",
        "rank_position": 1,
        "tags": ["lofi", "study"],
        "failure_count": 0,
    }


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


async def test_get_random_track_falls_back_when_recent_filter_excludes_everything() -> None:
    pool = FakePool(fetchrow_results=[None, make_track_row(123)])
    repository = CatalogRepository(pool)

    result = await repository.get_random_track(guild_id=456, category_slug="chill")

    assert result is not None
    assert result.id == 123
    assert len(pool.fetchrow_calls) == 2
    recent_query, recent_args = pool.fetchrow_calls[0]
    fallback_query, fallback_args = pool.fetchrow_calls[1]
    assert "id NOT IN (SELECT track_id FROM recent)" in recent_query
    assert recent_args == (456, "chill", 10)
    assert "id NOT IN (SELECT track_id FROM recent)" not in fallback_query
    assert fallback_args == ("chill",)
