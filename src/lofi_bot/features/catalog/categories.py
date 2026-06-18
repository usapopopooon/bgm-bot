from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass(frozen=True)
class RankingCategory:
    slug: str
    label: str
    description: str
    fuzzytags: tuple[str, ...]


DEFAULT_CATEGORY = "chill"
JAMENDO_SEARCH_URL = "https://www.jamendo.com/search"

CATEGORIES: dict[str, RankingCategory] = {
    "chill": RankingCategory(
        slug="chill",
        label="Chill",
        description="Relaxed and calm tracks",
        fuzzytags=("chill", "relaxation", "calm"),
    ),
}


def get_category(slug: str) -> RankingCategory:
    try:
        return CATEGORIES[slug]
    except KeyError as error:
        allowed = ", ".join(CATEGORIES)
        raise ValueError(f"Unknown category {slug!r}. Allowed: {allowed}") from error


def build_category_source_url(category: RankingCategory) -> str:
    query_tags = (*category.fuzzytags, "instrumental")
    query = " ".join(dict.fromkeys(query_tags))
    return f"{JAMENDO_SEARCH_URL}?{urlencode({'qs': f'q={query}'})}"
