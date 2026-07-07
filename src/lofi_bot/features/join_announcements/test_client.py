from __future__ import annotations

from lofi_bot.features.join_announcements.client import (
    JoinAnnouncementClient,
    build_join_announcement_text,
)


class FakeResponse:
    status = 200

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def read(self) -> bytes:
        return b"wav"


class FakeSession:
    closed = False

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeResponse()

    async def close(self) -> None:
        self.closed = True


def test_build_join_announcement_text_trims_long_names() -> None:
    assert build_join_announcement_text("  Alice   Bob  ") == "Alice Bobさんが入室しました"
    assert build_join_announcement_text("") == "だれかさんが入室しました"


async def test_synthesize_join_sends_guild_id_and_throttles_consecutive_calls() -> None:
    session = FakeSession()
    client = JoinAnnouncementClient("http://tts-api", api_token="secret")
    client._session = session

    first = await client.synthesize_join(123, "Alice")
    second = await client.synthesize_join(123, "Bob")

    assert first == b"wav"
    assert second is None
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == "http://tts-api/synthesize"
    assert session.calls[0]["json"] == {
        "guild_id": 123,
        "text": "Aliceさんが入室しました",
        "cache": True,
    }
    assert session.calls[0]["headers"] == {"Authorization": "Bearer secret"}
