from __future__ import annotations

import asyncio

from lofi_bot.features.join_announcements import client as client_module
from lofi_bot.features.join_announcements.client import (
    JoinAnnouncementClient,
    build_join_announcement_text,
    build_leave_announcement_text,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"wav",
        read_started: asyncio.Event | None = None,
        read_allowed: asyncio.Event | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self._read_started = read_started
        self._read_allowed = read_allowed

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def read(self) -> bytes:
        if self._read_started is not None:
            self._read_started.set()
        if self._read_allowed is not None:
            await self._read_allowed.wait()
        return self._body


class FakeSession:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"wav",
        read_started: asyncio.Event | None = None,
        read_allowed: asyncio.Event | None = None,
    ) -> None:
        self.closed = False
        self._status = status
        self._body = body
        self._read_started = read_started
        self._read_allowed = read_allowed
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(
            status=self._status,
            body=self._body,
            read_started=self._read_started,
            read_allowed=self._read_allowed,
        )

    async def close(self) -> None:
        self.closed = True


def test_build_join_announcement_text_trims_long_names() -> None:
    assert build_join_announcement_text("  Alice   Bob  ") == "Alice Bobさんが入室しました"
    assert build_join_announcement_text("") == "だれかさんが入室しました"


def test_build_leave_announcement_text_trims_long_names() -> None:
    assert build_leave_announcement_text("  Alice   Bob  ") == "Alice Bobさんが退室しました"
    assert build_leave_announcement_text("") == "だれかさんが退室しました"


async def test_synthesize_join_sends_guild_id_for_consecutive_calls(monkeypatch) -> None:
    monkeypatch.setattr(client_module, "JOIN_ANNOUNCEMENT_MIN_INTERVAL_SECONDS", 0)
    session = FakeSession()
    client = JoinAnnouncementClient("http://tts-api", api_token="secret")
    client._session = session

    first = await client.synthesize_join(123, "Alice")
    second = await client.synthesize_join(123, "Bob")

    assert first == b"wav"
    assert second == b"wav"
    assert len(session.calls) == 2
    assert session.calls[0]["url"] == "http://tts-api/synthesize"
    assert session.calls[0]["json"] == {
        "guild_id": 123,
        "text": "Aliceさんが入室しました",
        "cache": True,
    }
    assert session.calls[1]["json"] == {
        "guild_id": 123,
        "text": "Bobさんが入室しました",
        "cache": True,
    }
    assert session.calls[0]["headers"] == {"Authorization": "Bearer secret"}


async def test_synthesize_voice_events_queues_three_waiting_requests(monkeypatch) -> None:
    monkeypatch.setattr(client_module, "JOIN_ANNOUNCEMENT_MIN_INTERVAL_SECONDS", 0)
    read_started = asyncio.Event()
    read_allowed = asyncio.Event()
    session = FakeSession(read_started=read_started, read_allowed=read_allowed)
    client = JoinAnnouncementClient("http://tts-api")
    client._session = session

    first_task = asyncio.create_task(client.synthesize_join(123, "Alice"))
    await read_started.wait()
    queued_tasks = [
        asyncio.create_task(client.synthesize_leave(123, f"User {index}"))
        for index in range(3)
    ]
    await asyncio.sleep(0)

    dropped = await client.synthesize_join(123, "Dropped")
    read_allowed.set()
    results = await asyncio.gather(first_task, *queued_tasks)

    assert dropped is None
    assert results == [b"wav", b"wav", b"wav", b"wav"]
    assert [call["json"]["text"] for call in session.calls] == [
        "Aliceさんが入室しました",
        "User 0さんが退室しました",
        "User 1さんが退室しました",
        "User 2さんが退室しました",
    ]


async def test_synthesize_leave_sends_leave_text() -> None:
    session = FakeSession()
    client = JoinAnnouncementClient("http://tts-api", api_token="secret")
    client._session = session

    audio_data = await client.synthesize_leave(123, "Alice")

    assert audio_data == b"wav"
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == "http://tts-api/synthesize"
    assert session.calls[0]["json"] == {
        "guild_id": 123,
        "text": "Aliceさんが退室しました",
        "cache": True,
    }
    assert session.calls[0]["headers"] == {"Authorization": "Bearer secret"}


async def test_probe_startup_synthesis_fetches_audio_without_guild_id() -> None:
    session = FakeSession()
    client = JoinAnnouncementClient("http://tts-api", api_token="secret")
    client._session = session

    assert await client.probe_startup_synthesis() is True

    assert len(session.calls) == 1
    assert session.calls[0]["url"] == "http://tts-api/synthesize"
    assert session.calls[0]["json"] == {
        "text": "疎通確認さんが入室しました",
        "cache": True,
    }
    assert session.calls[0]["headers"] == {"Authorization": "Bearer secret"}


async def test_probe_startup_synthesis_returns_false_when_disabled() -> None:
    session = FakeSession()
    client = JoinAnnouncementClient("")
    client._session = session

    assert await client.probe_startup_synthesis() is False
    assert session.calls == []


async def test_probe_startup_synthesis_returns_false_for_empty_audio() -> None:
    session = FakeSession(body=b"")
    client = JoinAnnouncementClient("http://tts-api")
    client._session = session

    assert await client.probe_startup_synthesis() is False
