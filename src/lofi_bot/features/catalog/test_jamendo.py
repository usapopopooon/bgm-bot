from lofi_bot.features.catalog.categories import get_category
from lofi_bot.features.catalog.jamendo import JamendoClient


def test_build_params_uses_top_ranking_and_audio_format() -> None:
    client = JamendoClient("client-id")

    params = client.build_params(get_category("chill"), 500)

    assert params["client_id"] == "client-id"
    assert params["limit"] == 200
    assert params["order"] == "popularity_total"
    assert params["audioformat"] == "mp32"
    assert params["fuzzytags"] == "chill relaxation calm"
    assert params["vocalinstrumental"] == "instrumental"


def test_parse_track_extracts_metadata_and_tags() -> None:
    client = JamendoClient("client-id")

    track = client.parse_track(
        {
            "id": "1848357",
            "name": "Late Night Study",
            "artist_name": "Example Artist",
            "duration": 182,
            "audio": "https://audio.example/track.mp3",
            "shareurl": "https://www.jamendo.com/track/1848357",
            "license_ccurl": "https://creativecommons.org/licenses/by-nc-nd/3.0/",
            "musicinfo": {
                "tags": {
                    "genres": ["Lofi", "HipHop"],
                    "instruments": ["Piano"],
                    "vartags": ["lofi"],
                }
            },
        },
        "lofi",
        1,
    )

    assert track is not None
    assert track.provider_track_id == "1848357"
    assert track.title == "Late Night Study"
    assert track.artist == "Example Artist"
    assert track.tags == ("lofi", "hiphop", "piano")
