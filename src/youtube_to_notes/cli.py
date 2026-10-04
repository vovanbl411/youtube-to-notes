"""CLI: YouTube URL -> output/<video_id>/{metadata.json, transcript.md}."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import YouTubeToNotesError, __version__
from .transcript import (
    Fragment,
    fragments_from_json3,
    fragments_from_vtt,
    group_sections,
    render_metadata_json,
    render_transcript_md,
)
from .transcribe import transcribe_audio
from .youtube import (
    SubtitleTrack,
    download_audio,
    download_subtitles,
    extract_video_id,
    fetch_metadata,
    select_subtitle_track,
)

OUTPUT_DIR = Path("output")
SOURCE_BY_KIND = {"manual": "manual_subtitles", "auto": "automatic_subtitles"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-to-notes",
        description="Получить воспроизводимый transcript из YouTube URL (subtitles first).",
    )
    parser.add_argument("url", help="YouTube URL видео")
    parser.add_argument(
        "--model",
        default="small",
        help="Модель faster-whisper для fallback (по умолчанию small, CPU int8)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать существующий output/<video_id>/",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        video_id = extract_video_id(args.url)
    except YouTubeToNotesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        process(args.url, video_id, model=args.model, force=args.force)
    except YouTubeToNotesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def process(url: str, video_id: str, model: str = "small", force: bool = False) -> Path:
    out_dir = OUTPUT_DIR / video_id
    _check_existing(out_dir, force)
    video = fetch_metadata(url)
    _log(f"Видео: {video.title!r} — {video.channel}")
    track = select_subtitle_track(video)
    whisper_model = None
    with tempfile.TemporaryDirectory(prefix="youtube-to-notes-") as tmp:
        tmp_path = Path(tmp)
        if track:
            source = SOURCE_BY_KIND[track.kind]
            language = track.language
            sub_path, sub_format = download_subtitles(url, track, tmp_path)
            fragments = _parse_subtitles(sub_path, sub_format)
            _log(f"Субтитры: {source} [{track.key}], {len(fragments)} фрагментов")
        else:
            _log("Подходящие субтитры не найдены — Whisper fallback")
            audio_path = download_audio(url, tmp_path)
            fragments, language = transcribe_audio(audio_path, model)
            source = "whisper"
            whisper_model = model
            _log(f"Whisper [{model}]: язык {language or '?'}, {len(fragments)} сегментов")
    if not fragments:
        raise YouTubeToNotesError("Получен пустой transcript (нет текстовых фрагментов)")
    sections = group_sections(fragments)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metadata.json").write_text(
        render_metadata_json(video, language, source, whisper_model), encoding="utf-8"
    )
    (out_dir / "transcript.md").write_text(
        render_transcript_md(video, language, source, sections), encoding="utf-8"
    )
    _log(f"Готово: {out_dir} — {len(sections)} секций, источник {source}")
    return out_dir


def _parse_subtitles(path: Path, sub_format: str) -> list[Fragment]:
    content = path.read_text(encoding="utf-8")
    if sub_format == "json3":
        return fragments_from_json3(json.loads(content))
    return fragments_from_vtt(content)


def _check_existing(out_dir: Path, force: bool) -> None:
    if force or not out_dir.exists():
        return
    existing = [name for name in ("metadata.json", "transcript.md") if (out_dir / name).exists()]
    if existing:
        raise YouTubeToNotesError(
            f"Output уже существует: {out_dir} ({', '.join(existing)}). "
            "Используйте --force для перезаписи или удалите директорию."
        )


def _log(message: str) -> None:
    print(f"[youtube-to-notes] {message}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
