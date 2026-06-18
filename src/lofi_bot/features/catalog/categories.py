from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankingCategory:
    slug: str
    label: str
    description: str
    fuzzytags: tuple[str, ...]
    vocalinstrumental: str | None = None


DEFAULT_CATEGORY = "lofi"

CATEGORIES: dict[str, RankingCategory] = {
    "lofi": RankingCategory(
        slug="lofi",
        label="Lofi",
        description="Lofi, chillhop, mellow beats",
        fuzzytags=("lofi", "chillhop", "beats"),
    ),
    "chill": RankingCategory(
        slug="chill",
        label="Chill",
        description="Relaxed and calm tracks",
        fuzzytags=("chill", "relaxation", "calm"),
    ),
    "hiphop": RankingCategory(
        slug="hiphop",
        label="Hip Hop",
        description="Hip hop and beat-focused tracks",
        fuzzytags=("hiphop", "beats", "instrumental"),
    ),
    "relaxation": RankingCategory(
        slug="relaxation",
        label="Relaxation",
        description="Ambient and relaxing background music",
        fuzzytags=("relaxation", "ambient", "calm"),
    ),
    "instrumental": RankingCategory(
        slug="instrumental",
        label="Instrumental",
        description="Instrumental-only tracks",
        fuzzytags=("instrumental", "background", "soundtrack"),
        vocalinstrumental="instrumental",
    ),
    "beats": RankingCategory(
        slug="beats",
        label="Beats",
        description="Beats, hip hop, and electronic grooves",
        fuzzytags=("beats", "hiphop", "electronic"),
    ),
}


def get_category(slug: str) -> RankingCategory:
    try:
        return CATEGORIES[slug]
    except KeyError as error:
        allowed = ", ".join(CATEGORIES)
        raise ValueError(f"Unknown category {slug!r}. Allowed: {allowed}") from error
