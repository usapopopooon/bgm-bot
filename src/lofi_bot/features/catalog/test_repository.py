from __future__ import annotations

from lofi_bot.features.catalog.models import Track
from lofi_bot.features.catalog.repository import CatalogRepository


class FakePool:
    def __init__(self, *, fetchrow_results: list[dict[str, object] | None] | None = None) -> None:
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrow_results = fetchrow_results or []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        if "category_count" in query:
            return {"category_count": 0}
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None

    async def execute(self, query: str, *args: object) -> None:
        self.execute_calls.append((query, args))


class FakeAcquire:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    async def __aenter__(self) -> object:
        return self.connection

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeUpsertConnection:
    def __init__(self) -> None:
        self.fetched_at = object()
        self.fetchvals: list[str] = []
        self.executes: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def fetchval(self, query: str) -> object:
        self.fetchvals.append(query)
        return self.fetched_at

    async def execute(self, query: str, *args: object) -> None:
        self.executes.append((query, args))


class FakeUpsertPool:
    def __init__(self) -> None:
        self.connection = FakeUpsertConnection()

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.connection)


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
    assert len(pool.fetchrow_calls) == 1
    query, args = pool.fetchrow_calls[0]
    assert "tracks.instrumental_only = TRUE" in query
    assert args == (123, "chill")


async def test_get_random_track_excludes_tracks_played_since_current_fetch() -> None:
    pool = FakePool(fetchrow_results=[make_track_row(123)])
    repository = CatalogRepository(pool)

    result = await repository.get_random_track(guild_id=456, category_slug="chill")

    assert result is not None
    assert result.id == 123
    assert len(pool.fetchrow_calls) == 1
    query, args = pool.fetchrow_calls[0]
    assert "NOT EXISTS" in query
    assert "play_history.played_at >= tracks.fetched_at" in query
    assert args == (456, "chill")


async def test_get_any_random_track_selects_from_enabled_instrumental_cache() -> None:
    pool = FakePool(fetchrow_results=[make_track_row(123)])
    repository = CatalogRepository(pool)

    result = await repository.get_any_random_track(category_slug="chill")

    assert result is not None
    assert result.id == 123
    query, args = pool.fetchrow_calls[0]
    assert "instrumental_only = TRUE" in query
    assert "play_history" not in query
    assert args == ("chill",)


async def test_reset_play_history_deletes_guild_category_history() -> None:
    pool = FakePool()
    repository = CatalogRepository(pool)

    await repository.reset_play_history(guild_id=456, category_slug="chill")

    query, args = pool.execute_calls[0]
    assert "DELETE FROM play_history" in query
    assert args == (456, "chill")


async def test_upsert_tracks_uses_database_timestamp_for_catalog_generation() -> None:
    pool = FakeUpsertPool()
    repository = CatalogRepository(pool)
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

    count = await repository.upsert_tracks("chill", [track])

    assert count == 1
    assert pool.connection.fetchvals == ["SELECT now()"]
    insert_args = pool.connection.executes[0][1]
    assert insert_args[-1] is pool.connection.fetched_at
