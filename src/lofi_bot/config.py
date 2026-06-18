from __future__ import annotations

import os
from dataclasses import dataclass

from lofi_bot.features.catalog.categories import CATEGORIES, DEFAULT_CATEGORY


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    return int(value)


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _postgres_url_for_asyncpg(value: str) -> str:
    if value.startswith("postgresql+asyncpg://"):
        return value.replace("postgresql+asyncpg://", "postgresql://", 1)
    return value


@dataclass(frozen=True)
class Settings:
    discord_token: str
    jamendo_client_id: str
    database_url: str
    default_category: str
    jamendo_refresh_hour: int
    refresh_timezone: str
    jamendo_limit_per_category: int
    discord_guild_id: int | None
    sync_commands: bool


def load_settings() -> Settings:
    default_category = os.getenv("DEFAULT_CATEGORY", DEFAULT_CATEGORY).strip() or DEFAULT_CATEGORY
    if default_category not in CATEGORIES:
        allowed = ", ".join(CATEGORIES)
        raise RuntimeError(f"DEFAULT_CATEGORY must be one of: {allowed}")

    return Settings(
        discord_token=_required("DISCORD_TOKEN"),
        jamendo_client_id=_required("JAMENDO_CLIENT_ID"),
        database_url=_postgres_url_for_asyncpg(_required("DATABASE_URL")),
        default_category=default_category,
        jamendo_refresh_hour=int(os.getenv("JAMENDO_REFRESH_HOUR", "4")),
        refresh_timezone=os.getenv("REFRESH_TIMEZONE", "Asia/Tokyo"),
        jamendo_limit_per_category=int(os.getenv("JAMENDO_LIMIT_PER_CATEGORY", "200")),
        discord_guild_id=_optional_int("DISCORD_GUILD_ID"),
        sync_commands=_bool("SYNC_COMMANDS", True),
    )
