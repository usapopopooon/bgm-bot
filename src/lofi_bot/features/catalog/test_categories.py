from lofi_bot.features.catalog.categories import (
    CATEGORIES,
    DEFAULT_CATEGORY,
    build_category_source_url,
    get_category,
)


def test_categories_are_fixed_for_dropdown() -> None:
    assert list(CATEGORIES) == ["chill"]
    assert DEFAULT_CATEGORY == "chill"


def test_category_source_url_links_to_jamendo_search() -> None:
    category = get_category("chill")

    assert build_category_source_url(category) == "https://www.jamendo.com/search?q=chill"
