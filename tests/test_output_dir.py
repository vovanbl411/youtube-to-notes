import json
import socket

import pytest

from youtube_to_notes import cli, YouTubeToNotesError
from youtube_to_notes.cli import find_output_dir, output_dir_name, sanitize_title

METADATA = {
    "url": "https://www.youtube.com/watch?v=abc12345678",
    "video_id": "abc12345678",
    "title": "Test video",
    "channel": "Test channel",
    "upload_date": "2024-01-02",
    "duration": 761.0,
    "language": "ru",
    "transcript_source": "automatic_subtitles",
}

TRANSCRIPT = "# Transcript\n\n## 00:00\n\nНачало.\n"


def make_dir(tmp_path, name, metadata=METADATA, transcript=True, raw_metadata=None):
    out_dir = tmp_path / "output" / name
    out_dir.mkdir(parents=True)
    if raw_metadata is not None:
        (out_dir / "metadata.json").write_text(raw_metadata, encoding="utf-8")
    elif metadata is not None:
        (out_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
    if transcript:
        (out_dir / "transcript.md").write_text(TRANSCRIPT, encoding="utf-8")
    return out_dir


def no_network(*args, **kwargs):
    raise AssertionError("попытка сетевого доступа из --digest-request")


def patch_offline(monkeypatch):
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(cli, "fetch_metadata", no_network)
    monkeypatch.setattr(cli, "download_audio", no_network)
    monkeypatch.setattr(cli, "download_subtitles", no_network)
    monkeypatch.setattr(cli, "transcribe_audio", no_network)


# --- sanitize_title ---


def test_sanitize_normal_title_unchanged():
    title = "Подстановка данных из Secret в конфиги приложений."
    assert sanitize_title(title) == title
    assert output_dir_name(title, "D3csT2KvOS4") == f"{title}--D3csT2KvOS4"


def test_sanitize_replaces_slashes():
    assert sanitize_title("часть 1/2 \\ остальное") == "часть 1-2 - остальное"


def test_sanitize_collapses_whitespace():
    assert sanitize_title("  a \n\t b   c ") == "a b c"


def test_sanitize_removes_control_characters():
    assert sanitize_title("a\x00b\x07c\n") == "abc"


def test_sanitize_preserves_unicode():
    title = "日本語のタイトル — π Æ ø"
    assert sanitize_title(title) == title


def test_sanitize_truncation_is_deterministic():
    assert sanitize_title("x" * 250) == "x" * cli.TITLE_MAX_CHARS
    assert sanitize_title("a" * 99 + " " + "b" * 50) == "a" * 99
    long_title = "слово " * 40
    assert sanitize_title(long_title) == sanitize_title(long_title)
    assert len(sanitize_title(long_title)) == cli.TITLE_MAX_CHARS


def test_sanitize_empty_title_falls_back():
    assert sanitize_title("") == "video"
    assert sanitize_title("   ") == "video"
    assert sanitize_title("\x00\x1f") == "video"
    assert output_dir_name("   ", "abc12345678") == "video--abc12345678"


# --- find_output_dir ---


def test_find_output_dir_new_naming(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    make_dir(tmp_path, "Test video--abc12345678")
    assert find_output_dir("abc12345678") == tmp_path / "output" / "Test video--abc12345678"


def test_find_output_dir_legacy_naming(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    make_dir(tmp_path, "abc12345678")
    assert find_output_dir("abc12345678") == tmp_path / "output" / "abc12345678"


def test_find_output_dir_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / "output").mkdir()
    with pytest.raises(YouTubeToNotesError, match="не найден"):
        find_output_dir("abc12345678")


def test_find_output_dir_ambiguous(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    make_dir(tmp_path, "Один--abc12345678")
    make_dir(tmp_path, "Два--abc12345678")
    with pytest.raises(YouTubeToNotesError) as exc_info:
        find_output_dir("abc12345678")
    message = str(exc_info.value)
    assert "несколько output" in message
    assert "Один--abc12345678" in message and "Два--abc12345678" in message


def test_find_output_dir_ignores_malformed_and_unrelated(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    make_dir(tmp_path, "битый", raw_metadata="{не json")
    make_dir(tmp_path, "не-то-видео", metadata={**METADATA, "video_id": "xyz98765432"})
    make_dir(tmp_path, "без-metadata", metadata=None)
    correct = make_dir(tmp_path, "Правильный--abc12345678")
    assert find_output_dir("abc12345678") == correct


# --- CLI integration ---


def test_digest_request_finds_new_naming_directory(tmp_path, monkeypatch):
    out_dir = make_dir(tmp_path, "Test video--abc12345678")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    patch_offline(monkeypatch)

    assert cli.main(["--digest-request", "abc12345678"]) == 0
    assert (out_dir / "digest-request.md").exists()


def test_digest_request_finds_legacy_directory(tmp_path, monkeypatch):
    out_dir = make_dir(tmp_path, "abc12345678")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    patch_offline(monkeypatch)

    assert cli.main(["--digest-request", "abc12345678"]) == 0
    assert (out_dir / "digest-request.md").exists()
