from __future__ import annotations

from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class GuildSettings:
    guild_id: int
    voice_channel_id: int | None
    selected_category: str
    volume: float
    stay_connected: bool
    panel_channel_id: int | None
    panel_message_id: int | None
    member_commands_enabled: bool = False


class GuildSettingsRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_or_create(self, guild_id: int, default_category: str) -> GuildSettings:
        row = await self._pool.fetchrow(
            """
            INSERT INTO guild_settings (guild_id, selected_category)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE
            SET guild_id = EXCLUDED.guild_id
            RETURNING *
            """,
            guild_id,
            default_category,
        )
        return self._row_to_settings(row)

    async def update_voice_channel(self, guild_id: int, voice_channel_id: int) -> None:
        await self._pool.execute(
            """
            UPDATE guild_settings
            SET voice_channel_id = $2,
                updated_at = now()
            WHERE guild_id = $1
            """,
            guild_id,
            voice_channel_id,
        )

    async def clear_voice_channel(self, guild_id: int) -> None:
        await self._pool.execute(
            """
            UPDATE guild_settings
            SET voice_channel_id = NULL,
                updated_at = now()
            WHERE guild_id = $1
            """,
            guild_id,
        )

    async def update_selected_category(self, guild_id: int, category_slug: str) -> None:
        await self._pool.execute(
            """
            UPDATE guild_settings
            SET selected_category = $2,
                updated_at = now()
            WHERE guild_id = $1
            """,
            guild_id,
            category_slug,
        )

    async def update_volume(self, guild_id: int, volume: float) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, volume)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE
            SET volume = EXCLUDED.volume,
                updated_at = now()
            """,
            guild_id,
            volume,
        )

    async def update_stay_connected(self, guild_id: int, stay_connected: bool) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, stay_connected)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE
            SET stay_connected = EXCLUDED.stay_connected,
                updated_at = now()
            """,
            guild_id,
            stay_connected,
        )

    async def update_member_commands_enabled(
        self,
        guild_id: int,
        member_commands_enabled: bool,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, member_commands_enabled)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE
            SET member_commands_enabled = EXCLUDED.member_commands_enabled,
                updated_at = now()
            """,
            guild_id,
            member_commands_enabled,
        )

    async def list_stay_connected(self) -> list[GuildSettings]:
        rows = await self._pool.fetch(
            """
            SELECT *
            FROM guild_settings
            WHERE stay_connected = TRUE
              AND voice_channel_id IS NOT NULL
            ORDER BY guild_id
            """
        )
        return [self._row_to_settings(row) for row in rows]

    async def update_panel(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO guild_settings (guild_id, panel_channel_id, panel_message_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id) DO UPDATE
            SET panel_channel_id = EXCLUDED.panel_channel_id,
                panel_message_id = EXCLUDED.panel_message_id,
                updated_at = now()
            """,
            guild_id,
            channel_id,
            message_id,
        )

    def _row_to_settings(self, row: asyncpg.Record) -> GuildSettings:
        return GuildSettings(
            guild_id=row["guild_id"],
            voice_channel_id=row["voice_channel_id"],
            selected_category=row["selected_category"],
            volume=row["volume"],
            stay_connected=row["stay_connected"],
            panel_channel_id=row["panel_channel_id"],
            panel_message_id=row["panel_message_id"],
            member_commands_enabled=row["member_commands_enabled"],
        )
