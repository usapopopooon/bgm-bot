from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Track:
    provider_track_id: str
    title: str
    artist: str
    audio_url: str
    share_url: str
    license_url: str | None
    duration_seconds: int
    ranking_category: str
    rank_position: int
    tags: tuple[str, ...] = field(default_factory=tuple)
    id: int | None = None
    failure_count: int = 0
