from lofi_bot.features.catalog.categories import (
    CATEGORIES,
    DEFAULT_CATEGORY,
    build_category_source_url,
    get_category,
)


def test_categories_are_fixed_for_dropdown() -> None:
    assert list(CATEGORIES) == [
        "lofi",
        "chill",
        "hiphop",
        "relaxation",
        "instrumental",
        "beats",
    ]
    assert DEFAULT_CATEGORY == "lofi"


def test_instrumental_category_uses_instrumental_filter() -> None:
    category = get_category("instrumental")

    assert category.vocalinstrumental == "instrumental"
    assert "instrumental" in category.fuzzytags


def test_category_source_url_links_to_jamendo_search() -> None:
    category = get_category("lofi")

    assert build_category_source_url(category) == (
        "https://www.jamendo.com/search?qs=q%3Dlofi+chillhop+beats"
    )
