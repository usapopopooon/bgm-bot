from __future__ import annotations

import asyncio
import logging

import asyncpg

LOGGER = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str) -> None:
        self._url = url
        self.pool: asyncpg.Pool | None = None

    async def connect(self, *, attempts: int = 30, delay_seconds: float = 2.0) -> None:
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                self.pool = await asyncpg.create_pool(self._url, min_size=1, max_size=5)
                return
            except (OSError, asyncpg.PostgresConnectionError) as error:
                last_error = error
                if attempt >= attempts:
                    break
                LOGGER.warning(
                    "Database is not ready yet (%s/%s): %s",
                    attempt,
                    attempts,
                    error,
                )
                await asyncio.sleep(delay_seconds)

        raise RuntimeError("Database did not become ready") from last_error

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    async def migrate(self) -> None:
        if self.pool is None:
            raise RuntimeError("Database pool is not connected")

        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tracks (
                    id BIGSERIAL PRIMARY KEY,
                    provider TEXT NOT NULL DEFAULT 'jamendo',
                    provider_track_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    audio_url TEXT NOT NULL,
                    share_url TEXT NOT NULL,
                    license_url TEXT,
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    ranking_category TEXT NOT NULL,
                    rank_position INTEGER NOT NULL DEFAULT 0,
                    tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_failed_at TIMESTAMPTZ,
                    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (provider, provider_track_id, ranking_category)
                );

                CREATE INDEX IF NOT EXISTS idx_tracks_category_enabled_rank
                    ON tracks (ranking_category, enabled, rank_position);

                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id BIGINT PRIMARY KEY,
                    voice_channel_id BIGINT,
                    selected_category TEXT NOT NULL DEFAULT 'lofi',
                    volume REAL NOT NULL DEFAULT 0.01,
                    panel_channel_id BIGINT,
                    panel_message_id BIGINT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                ALTER TABLE guild_settings
                    ALTER COLUMN volume SET DEFAULT 0.01;

                CREATE TABLE IF NOT EXISTS play_history (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    track_id BIGINT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                    ranking_category TEXT NOT NULL,
                    played_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                CREATE INDEX IF NOT EXISTS idx_play_history_guild_played
                    ON play_history (guild_id, played_at DESC);
                """
            )
