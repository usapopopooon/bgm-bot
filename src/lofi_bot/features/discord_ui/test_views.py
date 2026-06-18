from __future__ import annotations

from lofi_bot.features.discord_ui.views import build_panel_embed
from lofi_bot.features.guild_settings.repository import GuildSettings


class FakeGuildSettingsRepository:
    async def get_or_create(self, guild_id: int, default_category: str) -> GuildSettings:
        return GuildSettings(
            guild_id=guild_id,
            voice_channel_id=None,
            selected_category=default_category,
            volume=0.01,
            stay_connected=False,
            panel_channel_id=None,
            panel_message_id=None,
        )


class FakePlayerManager:
    def current_track(self, guild_id: int):
        return None


async def test_panel_embed_includes_source_link_without_category_field() -> None:
    embed = await build_panel_embed(
        guild_id=123,
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(),
        default_category="chill",
    )

    fields = {field.name: field.value for field in embed.fields}

    assert "Category" not in fields
    assert fields["Source"] == (
        "[Jamendo: Chill](https://www.jamendo.com/search?qs=q%3Dchill+relaxation+calm+instrumental)"
    )
    assert fields["Stay"] == "OFF"
    assert fields["Now Playing"] == "準備中"
