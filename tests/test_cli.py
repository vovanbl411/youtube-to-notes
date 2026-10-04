import json

from youtube_to_notes import cli
from youtube_to_notes.transcript import Fragment
from youtube_to_notes.youtube import SubtitleTrack, Video

JSON3 = {
    "events": [
        {"tStartMs": 0, "dDurationMs": 4000, "segs": [{"utf8": "Текст первого фрагмента."}]},
        {"tStartMs": 42, "dDurationMs": 3000, "segs": [{"utf8": "Следующий фрагмент."}]},
    ]
}

FORMATS = [{"ext": "json3", "url": "https://example.com/subs"}]
URL = "https://www.youtube.com/watch?v=abc12345678"


def make_video(subtitles=None, automatic_captions=None):
    return Video(
        video_id="abc12345678",
        url=URL,
        title="Test",
        channel="Test channel",
        upload_date="20240102",
        duration=60.0,
        language="ru",
        subtitles=subtitles or {},
        automatic_captions=automatic_captions or {},
    )


def fail(*args, **kwargs):
    raise AssertionError("не должен вызываться на этом пути")


def test_invalid_url_returns_exit_code_2(capsys):
    assert cli.main(["https://example.com/nope"]) == 2
    assert "error:" in capsys.readouterr().err


def test_subtitles_path_skips_audio_and_whisper(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "fetch_metadata", lambda url, cookies_from_browser=None: make_video(subtitles={"ru": FORMATS})
    )
    monkeypatch.setattr(cli, "download_audio", fail)
    monkeypatch.setattr(cli, "transcribe_audio", fail)

    def fake_download_subtitles(url, track, dest_dir, cookies_from_browser=None):
        assert isinstance(track, SubtitleTrack)
        path = dest_dir / "subs.ru.json3"
        path.write_text(json.dumps(JSON3), encoding="utf-8")
        return path, "json3"

    monkeypatch.setattr(cli, "download_subtitles", fake_download_subtitles)

    assert cli.main([URL]) == 0
    out_dir = tmp_path / "output" / "Test--abc12345678"
    metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["transcript_source"] == "manual_subtitles"
    assert metadata["language"] == "ru"
    transcript = (out_dir / "transcript.md").read_text(encoding="utf-8")
    assert "## 00:00" in transcript
    assert "Текст первого фрагмента." in transcript
    assert list(out_dir.iterdir()) and sorted(p.name for p in out_dir.iterdir()) == [
        "metadata.json",
        "transcript.md",
    ]


def test_whisper_fallback_used_without_subtitles(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "fetch_metadata", lambda url, cookies_from_browser=None: make_video()
    )
    monkeypatch.setattr(cli, "download_subtitles", fail)

    def fake_download_audio(url, dest_dir, cookies_from_browser=None):
        seen["cookies"] = cookies_from_browser
        return dest_dir / "audio.m4a"

    monkeypatch.setattr(cli, "download_audio", fake_download_audio)
    monkeypatch.setattr(
        cli,
        "transcribe_audio",
        lambda audio_path, model: ([Fragment(0, 5, "Hello world."), Fragment(10, 15, "Second.")], "en"),
    )

    assert cli.main([URL]) == 0
    assert seen["cookies"] is None
    out_dir = tmp_path / "output" / "Test--abc12345678"
    metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["transcript_source"] == "whisper"
    assert metadata["whisper_model"] == "small"
    assert metadata["language"] == "en"
    assert "## 00:00" in (out_dir / "transcript.md").read_text(encoding="utf-8")
    assert cli.main([URL, "--force", "--cookies-from-browser", "firefox"]) == 0
    assert seen["cookies"] == "firefox"


def test_rerun_refuses_without_force(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli,
        "fetch_metadata",
        lambda url, cookies_from_browser=None: make_video(subtitles={"ru": FORMATS}),
    )

    def fake_download_subtitles(url, track, dest_dir, cookies_from_browser=None):
        path = dest_dir / "subs.ru.json3"
        path.write_text(json.dumps(JSON3), encoding="utf-8")
        return path, "json3"

    monkeypatch.setattr(cli, "download_subtitles", fake_download_subtitles)

    assert cli.main([URL]) == 0
    assert cli.main([URL]) == 1
    assert "--force" in capsys.readouterr().err
    assert cli.main([URL, "--force"]) == 0


def test_output_path_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "fetch_metadata", lambda url, cookies_from_browser=None: make_video()
    )
    monkeypatch.setattr(
        cli,
        "download_audio",
        lambda url, dest_dir, cookies_from_browser=None: dest_dir / "audio.m4a",
    )
    monkeypatch.setattr(cli, "transcribe_audio", lambda audio_path, model: ([Fragment(0, 5, "x")], "en"))

    for _ in range(2):
        assert cli.main([URL, "--force"]) == 0
    dirs = [d.name for d in (tmp_path / "output").iterdir()]
    assert dirs == ["Test--abc12345678"]
