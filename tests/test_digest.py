import json
import socket

import pytest

from youtube_to_notes import cli
from youtube_to_notes.digest import render_digest_request_md

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

WHISPER_METADATA = {**METADATA, "transcript_source": "whisper", "whisper_model": "small"}

TRANSCRIPT = (
    "---\n"
    "source: https://www.youtube.com/watch?v=abc12345678\n"
    'title: "Test video"\n'
    "---\n"
    "\n"
    "# Transcript\n"
    "\n"
    "## 00:00\n"
    "\n"
    "Начало.\n"
    "\n"
    "## 12:41\n"
    "\n"
    "Важная мысль.\n"
)


def make_output(tmp_path, metadata):
    out_dir = tmp_path / "output" / metadata["video_id"]
    out_dir.mkdir(parents=True)
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "transcript.md").write_text(TRANSCRIPT, encoding="utf-8")
    return out_dir


def no_network(*args, **kwargs):
    raise AssertionError("попытка сетевого доступа из digest-request")


def patch_offline(monkeypatch):
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(cli, "fetch_metadata", no_network)
    monkeypatch.setattr(cli, "download_audio", no_network)
    monkeypatch.setattr(cli, "download_subtitles", no_network)
    monkeypatch.setattr(cli, "transcribe_audio", no_network)


def test_reads_metadata_json_and_includes_fields(tmp_path, monkeypatch):
    out_dir = make_output(tmp_path, METADATA)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    patch_offline(monkeypatch)

    assert cli.main(["--digest-request", METADATA["video_id"]]) == 0
    request = (out_dir / "digest-request.md").read_text(encoding="utf-8")
    assert f"- URL: {METADATA['url']}" in request
    assert f"- Video ID: {METADATA['video_id']}" in request
    assert f"- Title: {METADATA['title']}" in request
    assert f"- Channel: {METADATA['channel']}" in request
    assert "- Upload date: 2024-01-02" in request
    assert "- Duration: 12:41 (761 с)" in request
    assert "- Language: ru" in request
    assert "- Transcript source: automatic_subtitles" in request


def test_includes_full_transcript_verbatim(tmp_path, monkeypatch):
    out_dir = make_output(tmp_path, METADATA)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    patch_offline(monkeypatch)

    assert cli.main(["--digest-request", METADATA["video_id"]]) == 0
    request = (out_dir / "digest-request.md").read_text(encoding="utf-8")
    assert "## Transcript" in request
    assert TRANSCRIPT.rstrip("\n") in request


def test_whisper_model_present_only_when_in_metadata(tmp_path, monkeypatch):
    out_dir = make_output(tmp_path, METADATA)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    patch_offline(monkeypatch)

    assert cli.main(["--digest-request", METADATA["video_id"]]) == 0
    request_path = out_dir / "digest-request.md"
    assert "- Whisper model" not in request_path.read_text(encoding="utf-8")

    (out_dir / "metadata.json").write_text(
        json.dumps(WHISPER_METADATA, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert cli.main(["--digest-request", METADATA["video_id"], "--force"]) == 0
    request = request_path.read_text(encoding="utf-8")
    assert "- Whisper model: small" in request
    assert "- Transcript source: whisper" in request
    assert "transcript_source: whisper" in request


def test_deterministic_output(tmp_path, monkeypatch):
    out_dir = make_output(tmp_path, METADATA)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    patch_offline(monkeypatch)

    first = render_digest_request_md(
        json.loads((out_dir / "metadata.json").read_text(encoding="utf-8")),
        (out_dir / "transcript.md").read_text(encoding="utf-8"),
    )
    assert cli.main(["--digest-request", METADATA["video_id"]]) == 0
    assert (out_dir / "digest-request.md").read_text(encoding="utf-8") == first
    assert cli.main(["--digest-request", METADATA["video_id"], "--force"]) == 0
    assert (out_dir / "digest-request.md").read_text(encoding="utf-8") == first


def test_refuses_to_overwrite_without_force(tmp_path, monkeypatch, capsys):
    out_dir = make_output(tmp_path, METADATA)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    patch_offline(monkeypatch)
    before = (out_dir / "metadata.json").read_bytes(), (out_dir / "transcript.md").read_bytes()

    assert cli.main(["--digest-request", METADATA["video_id"]]) == 0
    request_path = out_dir / "digest-request.md"
    written = request_path.read_bytes()
    assert cli.main(["--digest-request", METADATA["video_id"]]) == 1
    assert "--force" in capsys.readouterr().err
    assert request_path.read_bytes() == written
    assert cli.main(["--digest-request", METADATA["video_id"], "--force"]) == 0
    assert request_path.read_bytes() == written
    assert (out_dir / "metadata.json").read_bytes() == before[0]
    assert (out_dir / "transcript.md").read_bytes() == before[1]


def test_missing_transcript_output_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    patch_offline(monkeypatch)
    (tmp_path / "output" / "abc12345678").mkdir(parents=True)

    assert cli.main(["--digest-request", "abc12345678"]) == 1
    err = capsys.readouterr().err
    assert "metadata.json" in err and "transcript.md" in err
    assert not (tmp_path / "output" / "abc12345678" / "digest-request.md").exists()


def test_no_network_or_llm_calls(tmp_path, monkeypatch):
    make_output(tmp_path, METADATA)
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    patch_offline(monkeypatch)

    assert cli.main(["--digest-request", METADATA["video_id"], "--force"]) == 0
    assert (tmp_path / "output" / "abc12345678" / "digest-request.md").exists()


def test_digest_request_rejects_url_combination(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--digest-request", "abc12345678", "https://www.youtube.com/watch?v=abc12345678"])
    assert exc_info.value.code == 2
    assert "--digest-request" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code == 2


def test_null_metadata_fields_rendered_as_null():
    metadata = {**METADATA, "upload_date": None, "duration": None}
    request = render_digest_request_md(metadata, TRANSCRIPT)
    assert "- Upload date: null" in request
    assert "- Duration: null" in request
    assert "Whisper model" not in request
