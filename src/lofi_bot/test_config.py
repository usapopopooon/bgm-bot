from __future__ import annotations

import pytest

from lofi_bot.config import load_settings

BASE_ENV = {
    "DISCORD_TOKEN": "discord-token",
    "JAMENDO_CLIENT_ID": "jamendo-client-id",
}


def test_load_settings_uses_explicit_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "os.environ",
        {
            **BASE_ENV,
            "DATABASE_URL": "postgresql+asyncpg://user:password@example:5432/app",
        },
    )

    settings = load_settings()

    assert settings.database_url == "postgresql://user:password@example:5432/app"


def test_load_settings_builds_database_url_from_postgres_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "os.environ",
        {
            **BASE_ENV,
            "POSTGRES_HOST": "lofi-postgres",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "lofi",
            "POSTGRES_USER": "lofi",
            "POSTGRES_PASSWORD": "pass with symbols/@",
        },
    )

    settings = load_settings()

    assert settings.database_url == (
        "postgresql://lofi:pass%20with%20symbols%2F%40@lofi-postgres:5432/lofi"
    )
