from __future__ import annotations

import logging
import re
import time

import aiohttp

LOGGER = logging.getLogger(__name__)
JOIN_ANNOUNCEMENT_TIMEOUT_SECONDS = 5.0
JOIN_ANNOUNCEMENT_MIN_INTERVAL_SECONDS = 2.0
MAX_DISPLAY_NAME_LENGTH = 32
STARTUP_PROBE_DISPLAY_NAME = "疎通確認"
_WHITESPACE_PATTERN = re.compile(r"\s+")


def build_join_announcement_text(display_name: str) -> str:
    return _build_voice_event_announcement_text(display_name, "入室")


def build_leave_announcement_text(display_name: str) -> str:
    return _build_voice_event_announcement_text(display_name, "退室")


def _build_voice_event_announcement_text(display_name: str, event_name: str) -> str:
    normalized = _WHITESPACE_PATTERN.sub(" ", display_name).strip()
    if not normalized:
        normalized = "だれか"
    if len(normalized) > MAX_DISPLAY_NAME_LENGTH:
        normalized = normalized[:MAX_DISPLAY_NAME_LENGTH]
    return f"{normalized}さんが{event_name}しました"


class JoinAnnouncementClient:
    def __init__(
        self,
        api_url: str | None,
        *,
        api_token: str = "",
    ) -> None:
        self._api_url = api_url.rstrip("/") if api_url else ""
        self._api_token = api_token
        self._session: aiohttp.ClientSession | None = None
        self._in_flight_guilds: set[int] = set()
        self._last_started_at_by_guild: dict[int, float] = {}

    @property
    def is_enabled(self) -> bool:
        return bool(self._api_url)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def synthesize_join(self, guild_id: int, display_name: str) -> bytes | None:
        return await self._synthesize_voice_event(
            guild_id,
            build_join_announcement_text(display_name),
            failure_context="Join announcement TTS",
        )

    async def synthesize_leave(self, guild_id: int, display_name: str) -> bytes | None:
        return await self._synthesize_voice_event(
            guild_id,
            build_leave_announcement_text(display_name),
            failure_context="Leave announcement TTS",
        )

    async def _synthesize_voice_event(
        self,
        guild_id: int,
        announcement_text: str,
        *,
        failure_context: str,
    ) -> bytes | None:
        if not self.is_enabled:
            return None
        if not self._try_begin_request(guild_id):
            return None

        try:
            return await self._request_synthesis(
                {
                    "guild_id": guild_id,
                    "text": announcement_text,
                    "cache": True,
                },
                failure_context=failure_context,
            )
        finally:
            self._in_flight_guilds.discard(guild_id)

    async def probe_startup_synthesis(self) -> bool:
        if not self.is_enabled:
            return False

        audio_data = await self._request_synthesis(
            {
                "text": build_join_announcement_text(STARTUP_PROBE_DISPLAY_NAME),
                "cache": True,
            },
            failure_context="Join announcement startup TTS probe",
        )
        if not audio_data:
            LOGGER.warning("Join announcement startup TTS probe returned empty audio")
            return False
        return True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=JOIN_ANNOUNCEMENT_TIMEOUT_SECONDS)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _request_synthesis(
        self,
        payload: dict[str, object],
        *,
        failure_context: str,
    ) -> bytes | None:
        headers = {}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"

        try:
            session = await self._get_session()
            async with session.post(
                f"{self._api_url}/synthesize",
                json=payload,
                headers=headers,
            ) as response:
                if response.status >= 400:
                    LOGGER.warning("%s failed status=%s", failure_context, response.status)
                    return None
                return await response.read()
        except (aiohttp.ClientError, TimeoutError):
            LOGGER.exception("%s request failed", failure_context)
            return None

    def _try_begin_request(self, guild_id: int) -> bool:
        now = time.monotonic()
        if guild_id in self._in_flight_guilds:
            return False
        last_started_at = self._last_started_at_by_guild.get(guild_id)
        if (
            last_started_at is not None
            and now - last_started_at < JOIN_ANNOUNCEMENT_MIN_INTERVAL_SECONDS
        ):
            return False
        self._in_flight_guilds.add(guild_id)
        self._last_started_at_by_guild[guild_id] = now
        return True
