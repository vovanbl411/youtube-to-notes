import pytest

import youtube_to_notes.youtube as youtube_module
from youtube_to_notes import YouTubeToNotesError
from youtube_to_notes.youtube import (
    Video,
    download_audio,
    download_subtitles,
    extract_video_id,
    fetch_metadata,
    select_subtitle_track,
)
from youtube_to_notes.youtube import SubtitleTrack

FORMATS = [{"ext": "json3", "url": "https://example.com/subs"}]
URL = "https://www.youtube.com/watch?v=abc12345678"


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
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=10s",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123",
    ],
)
def test_extract_video_id_supported_urls(url):
    assert extract_video_id(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
        "https://evilyoutu.be/dQw4w9WgXcQ",
        "https://vimeo.com/dQw4w9WgXcQ",
    ],
)
def test_extract_video_id_rejects_foreign_host_despite_valid_id(url):
    # video ID корректный (11 символов), но hostname не YouTube — должно быть отклонено
    with pytest.raises(YouTubeToNotesError):
        extract_video_id(url)


@pytest.mark.parametrize(
    "url",
    ["", "not a url", "https://www.youtube.com/no_id_here", "https://example.com/?v=short", "ftp://x"],
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


def _install_fake_ydl(monkeypatch):
    """Заменяет YoutubeDL на границе сети: захватывает opts, сеть не трогает."""
    captured = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {
                "id": "abc12345678",
                "title": "Test",
                "webpage_url": url,
                "channel": "Test channel",
                "duration": 60,
            }

        def prepare_filename(self, info):
            return "/nonexistent/audio.m4a"

    monkeypatch.setattr(youtube_module, "YoutubeDL", FakeYoutubeDL)
    return captured


def test_no_browser_cookies_by_default(monkeypatch, tmp_path):
    captured = _install_fake_ydl(monkeypatch)
    (tmp_path / "subs.ru.json3").write_text("{}", encoding="utf-8")
    (tmp_path / "audio.m4a").write_bytes(b"")
    track = SubtitleTrack("manual", "ru", "ru")

    fetch_metadata(URL)
    download_subtitles(URL, track, tmp_path)
    download_audio(URL, tmp_path)

    assert len(captured) == 3
    assert all("cookiesfrombrowser" not in opts for opts in captured)


def test_cookies_propagates_to_metadata_path(monkeypatch):
    captured = _install_fake_ydl(monkeypatch)
    fetch_metadata(URL, "firefox")
    assert captured[0]["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_cookies_propagates_to_subtitles_path(monkeypatch, tmp_path):
    captured = _install_fake_ydl(monkeypatch)
    (tmp_path / "subs.ru.json3").write_text("{}", encoding="utf-8")
    download_subtitles(URL, SubtitleTrack("manual", "ru", "ru"), tmp_path, "firefox")
    assert captured[0]["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_cookies_propagates_to_audio_path(monkeypatch, tmp_path):
    captured = _install_fake_ydl(monkeypatch)
    (tmp_path / "audio.m4a").write_bytes(b"")
    download_audio(URL, tmp_path, "firefox")
    assert captured[0]["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_unsupported_browser_rejected(monkeypatch):
    _install_fake_ydl(monkeypatch)
    with pytest.raises(YouTubeToNotesError, match="Неподдерживаемый браузер"):
        fetch_metadata(URL, "netscape")
