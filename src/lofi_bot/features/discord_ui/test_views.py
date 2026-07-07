from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from lofi_bot.features.catalog.models import Track
from lofi_bot.features.discord_ui.views import (
    PlayerControlView,
    build_panel_embed,
)
from lofi_bot.features.guild_settings.repository import GuildSettings


class FakeGuildSettingsRepository:
    def __init__(self, *, voice_event_sounds_enabled: bool = False) -> None:
        self.get_or_create_calls = 0
        self.updates: list[tuple[int, bool]] = []
        self._settings = GuildSettings(
            guild_id=123,
            voice_channel_id=None,
            selected_category="chill",
            volume=0.01,
            stay_connected=False,
            panel_channel_id=None,
            panel_message_id=None,
            voice_event_sounds_enabled=voice_event_sounds_enabled,
        )

    async def get_or_create(self, guild_id: int, default_category: str) -> GuildSettings:
        self.get_or_create_calls += 1
        return replace(self._settings, guild_id=guild_id, selected_category=default_category)

    async def update_voice_event_sounds_enabled(
        self,
        guild_id: int,
        voice_event_sounds_enabled: bool,
    ) -> None:
        self.updates.append((guild_id, voice_event_sounds_enabled))
        self._settings = replace(
            self._settings,
            guild_id=guild_id,
            voice_event_sounds_enabled=voice_event_sounds_enabled,
        )


class FakePlayerManager:
    def __init__(self, track: Track | None = None, is_paused: bool = False) -> None:
        self.track = track
        self._is_paused = is_paused

    async def toggle_pause(self, guild_id: int) -> bool:
        self._is_paused = not self._is_paused
        return True

    async def skip(self, guild_id: int) -> bool:
        return True

    def current_track(self, guild_id: int):
        return self.track

    def is_paused(self, guild_id: int) -> bool:
        return self._is_paused


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.edits: list[tuple[object, object]] = []

    async def send_message(self, message: str, *, ephemeral: bool = False) -> None:
        self.messages.append((message, ephemeral))

    async def edit_message(self, *, embed, view) -> None:  # noqa: ANN001
        self.edits.append((embed, view))


class FakeInteraction:
    def __init__(self, guild_id: int | None) -> None:
        self.guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
        self.response = FakeResponse()


async def test_panel_embed_uses_japanese_labels_without_admin_status() -> None:
    guild_settings = FakeGuildSettingsRepository()
    embed = await build_panel_embed(
        guild_id=123,
        guild_settings=guild_settings,
        player_manager=FakePlayerManager(),
        default_category="chill",
    )

    fields = {field.name: field.value for field in embed.fields}

    assert "Category" not in fields
    assert "Volume" not in fields
    assert "Stay" not in fields
    assert embed.title == "BGMボット"
    assert embed.description == "チル系のボーカルなし曲をランダムに再生します。"
    assert fields["検索元"] == "[Jamendo: chill](https://www.jamendo.com/search?q=chill)"
    assert fields["再生中"] == "準備中"
    assert "Progress" not in fields
    assert embed.footer.text == "パネルが流れたら /play で再投稿できます。"
    assert guild_settings.get_or_create_calls == 0


async def test_panel_embed_includes_current_track_without_progress_bar() -> None:
    track = Track(
        provider_track_id="jamendo-1",
        title="Morning Loop",
        artist="Cafe Artist",
        audio_url="https://example.com/audio.mp3",
        share_url="https://example.com/track",
        license_url=None,
        duration_seconds=200,
        ranking_category="chill",
        rank_position=1,
    )
    embed = await build_panel_embed(
        guild_id=123,
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(track=track),
        default_category="chill",
    )

    fields = {field.name: field.value for field in embed.fields}

    assert fields["再生中"] == "[Morning Loop](https://example.com/track)\nby Cafe Artist"
    assert "Progress" not in fields


async def test_player_control_view_includes_pause_and_next_buttons() -> None:
    view = PlayerControlView(
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(),
    )

    assert [item.label for item in view.children] == [
        "一時停止",
        "次の曲へ",
        "入退室音",
    ]
    assert [item.custom_id for item in view.children] == [
        "lofi_bot:pause",
        "lofi_bot:skip",
        "lofi_bot:voice_event_sounds",
    ]


async def test_player_control_view_shows_resume_when_paused() -> None:
    view = PlayerControlView(
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(is_paused=True),
        is_paused=True,
    )

    assert [item.label for item in view.children] == [
        "再開",
        "次の曲へ",
        "入退室音",
    ]


async def test_player_control_view_shows_voice_event_sound_status() -> None:
    view = PlayerControlView(
        guild_settings=FakeGuildSettingsRepository(),
        player_manager=FakePlayerManager(),
        voice_event_sounds_enabled=True,
    )

    assert view.children[2].label == "入退室音 ON"


async def test_voice_event_sounds_button_toggles_setting_and_updates_panel() -> None:
    guild_settings = FakeGuildSettingsRepository(voice_event_sounds_enabled=False)
    view = PlayerControlView(
        guild_settings=guild_settings,
        player_manager=FakePlayerManager(),
        voice_event_sounds_enabled=False,
    )
    interaction = FakeInteraction(guild_id=123)

    await view.children[2].callback(interaction)

    assert guild_settings.updates == [(123, True)]
    assert len(interaction.response.edits) == 1
    _embed, updated_view = interaction.response.edits[0]
    assert updated_view.children[2].label == "入退室音 ON"


async def test_pause_button_restores_voice_event_sound_status_from_repository() -> None:
    guild_settings = FakeGuildSettingsRepository(voice_event_sounds_enabled=True)
    view = PlayerControlView(
        guild_settings=guild_settings,
        player_manager=FakePlayerManager(),
    )
    interaction = FakeInteraction(guild_id=123)

    await view.children[0].callback(interaction)

    assert len(interaction.response.edits) == 1
    _embed, updated_view = interaction.response.edits[0]
    assert updated_view.children[2].label == "入退室音 ON"
