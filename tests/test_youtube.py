import pytest

from youtube_to_notes import YouTubeToNotesError
from youtube_to_notes.youtube import Video, extract_video_id, select_subtitle_track

FORMATS = [{"ext": "json3", "url": "https://example.com/subs"}]


def make_video(subtitles=None, automatic_captions=None, language=None):
    return Video(
        video_id="abc12345678",
        url="https://youtu.be/abc12345678",
        title="Test",
        channel="Test channel",
        upload_date="20240102",
        duration=100.0,
        language=language,
        subtitles=subtitles or {},
        automatic_captions=automatic_captions or {},
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=10s",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123",
    ],
)
def test_extract_video_id_supported_urls(url):
    assert extract_video_id(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    ["", "not a url", "https://vimeo.com/12345", "https://example.com/?v=short", "ftp://x"],
)
def test_extract_video_id_rejects_invalid(url):
    with pytest.raises(YouTubeToNotesError):
        extract_video_id(url)


def test_prefers_manual_over_auto():
    video = make_video(subtitles={"en": FORMATS}, automatic_captions={"ru": FORMATS})
    track = select_subtitle_track(video)
    assert (track.kind, track.language) == ("manual", "en")


def test_auto_uses_original_language_not_ru_translation():
    video = make_video(automatic_captions={"en": FORMATS, "ru": FORMATS}, language="en")
    track = select_subtitle_track(video)
    assert (track.kind, track.key) == ("auto", "en")


def test_detects_original_from_orig_suffix():
    video = make_video(automatic_captions={"en-orig": FORMATS, "ru": FORMATS})
    track = select_subtitle_track(video)
    assert (track.kind, track.key, track.language) == ("auto", "en-orig", "en")


def test_prefers_ru_then_en_when_no_original():
    video = make_video(automatic_captions={"fr": FORMATS, "ru": FORMATS, "en": FORMATS})
    assert select_subtitle_track(video).language == "ru"
    video = make_video(automatic_captions={"fr": FORMATS, "en": FORMATS})
    assert select_subtitle_track(video).language == "en"


def test_other_language_is_deterministic():
    video = make_video(automatic_captions={"fr": FORMATS, "de": FORMATS})
    assert select_subtitle_track(video).key == "de"


def test_no_tracks_returns_none():
    assert select_subtitle_track(make_video()) is None


def test_ignores_live_chat_and_empty_formats():
    video = make_video(subtitles={"live_chat": FORMATS, "ru": []})
    assert select_subtitle_track(video) is None
