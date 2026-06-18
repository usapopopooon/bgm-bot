from __future__ import annotations

from datetime import UTC, datetime

import asyncpg

from lofi_bot.features.catalog.categories import CATEGORIES
from lofi_bot.features.catalog.models import Track


class CatalogRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_tracks(self, category_slug: str, tracks: list[Track]) -> int:
        if not tracks:
            return 0

        fetched_at = datetime.now(UTC)
        async with self._pool.acquire() as connection, connection.transaction():
            for track in tracks:
                await connection.execute(
                    """
                    INSERT INTO tracks (
                        provider,
                        provider_track_id,
                        title,
                        artist,
                        audio_url,
                        share_url,
                        license_url,
                        duration_seconds,
                        ranking_category,
                        rank_position,
                        tags,
                        instrumental_only,
                        enabled,
                        fetched_at,
                        updated_at
                    ) VALUES (
                        'jamendo',
                        $1,
                        $2,
                        $3,
                        $4,
                        $5,
                        $6,
                        $7,
                        $8,
                        $9,
                        $10,
                        TRUE,
                        TRUE,
                        $11,
                        now()
                    )
                    ON CONFLICT (provider, provider_track_id, ranking_category)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        artist = EXCLUDED.artist,
                        audio_url = EXCLUDED.audio_url,
                        share_url = EXCLUDED.share_url,
                        license_url = EXCLUDED.license_url,
                        duration_seconds = EXCLUDED.duration_seconds,
                        rank_position = EXCLUDED.rank_position,
                        tags = EXCLUDED.tags,
                        instrumental_only = TRUE,
                        enabled = TRUE,
                        fetched_at = EXCLUDED.fetched_at,
                        updated_at = now()
                    """,
                    track.provider_track_id,
                    track.title,
                    track.artist,
                    track.audio_url,
                    track.share_url,
                    track.license_url,
                    track.duration_seconds,
                    category_slug,
                    track.rank_position,
                    list(track.tags),
                    fetched_at,
                )

            await connection.execute(
                """
                UPDATE tracks
                SET enabled = FALSE, updated_at = now()
                WHERE ranking_category = $1
                  AND fetched_at < $2
                """,
                category_slug,
                fetched_at,
            )
        return len(tracks)

    async def has_fresh_tracks(self, max_age_hours: int = 20) -> bool:
        row = await self._pool.fetchrow(
            """
            SELECT COUNT(DISTINCT ranking_category) AS category_count
            FROM tracks
            WHERE enabled = TRUE
              AND instrumental_only = TRUE
              AND fetched_at > now() - ($1::INT * interval '1 hour')
            """,
            max_age_hours,
        )
        return int(row["category_count"]) >= len(CATEGORIES)

    async def get_random_track(
        self,
        guild_id: int,
        category_slug: str,
        exclude_recent_count: int = 10,
    ) -> Track | None:
        row = await self._pool.fetchrow(
            """
            WITH recent AS (
                SELECT track_id
                FROM play_history
                WHERE guild_id = $1
                ORDER BY played_at DESC
                LIMIT $3
            )
            SELECT *
            FROM tracks
            WHERE ranking_category = $2
              AND enabled = TRUE
              AND instrumental_only = TRUE
              AND id NOT IN (SELECT track_id FROM recent)
            ORDER BY random()
            LIMIT 1
            """,
            guild_id,
            category_slug,
            exclude_recent_count,
        )
        if row is None:
            row = await self._pool.fetchrow(
                """
                SELECT *
                FROM tracks
                WHERE ranking_category = $1
                  AND enabled = TRUE
                  AND instrumental_only = TRUE
                ORDER BY random()
                LIMIT 1
                """,
                category_slug,
            )
        return self._row_to_track(row) if row is not None else None

    async def record_play(self, guild_id: int, track_id: int, category_slug: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO play_history (guild_id, track_id, ranking_category)
            VALUES ($1, $2, $3)
            """,
            guild_id,
            track_id,
            category_slug,
        )

    async def mark_failed(self, track_id: int) -> None:
        await self._pool.execute(
            """
            UPDATE tracks
            SET failure_count = failure_count + 1,
                last_failed_at = now(),
                enabled = CASE WHEN failure_count + 1 >= 5 THEN FALSE ELSE enabled END,
                updated_at = now()
            WHERE id = $1
            """,
            track_id,
        )

    def _row_to_track(self, row: asyncpg.Record) -> Track:
        return Track(
            id=row["id"],
            provider_track_id=row["provider_track_id"],
            title=row["title"],
            artist=row["artist"],
            audio_url=row["audio_url"],
            share_url=row["share_url"],
            license_url=row["license_url"],
            duration_seconds=row["duration_seconds"],
            ranking_category=row["ranking_category"],
            rank_position=row["rank_position"],
            tags=tuple(row["tags"] or ()),
            failure_count=row["failure_count"],
        )
