from __future__ import annotations

import logging
from typing import Any

import aiohttp

from lofi_bot.features.catalog.categories import RankingCategory
from lofi_bot.features.catalog.models import Track

LOGGER = logging.getLogger(__name__)


class JamendoAPIError(RuntimeError):
    pass


class JamendoClient:
    BASE_URL = "https://api.jamendo.com/v3.0/tracks/"

    def __init__(self, client_id: str) -> None:
        self._client_id = client_id
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> JamendoClient:
        timeout = aiohttp.ClientTimeout(total=30)
        self._session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._session is not None:
            await self._session.close()

    def build_params(self, category: RankingCategory, limit: int) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "client_id": self._client_id,
            "format": "json",
            "limit": max(1, min(limit, 200)),
            "order": "popularity_total",
            "include": "licenses musicinfo",
            "audioformat": "mp32",
            "groupby": "artist_id",
            "type": "single albumtrack",
            "fuzzytags": " ".join(category.fuzzytags),
            "vocalinstrumental": "instrumental",
        }
        return params

    async def fetch_top_tracks(self, category: RankingCategory, limit: int) -> list[Track]:
        if self._session is None:
            raise RuntimeError("JamendoClient must be used as an async context manager")

        params = self.build_params(category, limit)
        LOGGER.info("Refreshing Jamendo category=%s limit=%s", category.slug, params["limit"])
        async with self._session.get(self.BASE_URL, params=params) as response:
            response.raise_for_status()
            payload = await response.json()

        headers = payload.get("headers", {})
        if headers.get("status") != "success":
            raise JamendoAPIError(headers.get("error_message") or "Jamendo API request failed")

        tracks: list[Track] = []
        for rank_position, item in enumerate(payload.get("results", []), start=1):
            track = self.parse_track(item, category.slug, rank_position)
            if track is not None:
                tracks.append(track)
        return tracks

    def parse_track(
        self,
        item: dict[str, Any],
        category_slug: str,
        rank_position: int,
    ) -> Track | None:
        audio_url = str(item.get("audio") or "")
        share_url = str(item.get("shareurl") or item.get("shorturl") or "")
        provider_track_id = str(item.get("id") or "")
        if not audio_url or not share_url or not provider_track_id:
            return None

        title = str(item.get("name") or "Untitled").strip() or "Untitled"
        artist = str(item.get("artist_name") or "Unknown Artist").strip() or "Unknown Artist"

        return Track(
            provider_track_id=provider_track_id,
            title=title,
            artist=artist,
            audio_url=audio_url,
            share_url=share_url,
            license_url=item.get("license_ccurl"),
            duration_seconds=int(item.get("duration") or 0),
            ranking_category=category_slug,
            rank_position=rank_position,
            tags=self._extract_tags(item),
        )

    def _extract_tags(self, item: dict[str, Any]) -> tuple[str, ...]:
        musicinfo = item.get("musicinfo") or {}
        raw_tags = musicinfo.get("tags") or {}
        tags: list[str] = []
        if isinstance(raw_tags, dict):
            for value in raw_tags.values():
                if isinstance(value, list):
                    tags.extend(str(tag) for tag in value if tag)
        return tuple(dict.fromkeys(tag.strip().lower() for tag in tags if tag.strip()))
