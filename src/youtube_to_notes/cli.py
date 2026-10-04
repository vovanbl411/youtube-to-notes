"""CLI: YouTube URL -> output/<sanitized-title>--<video_id>/{metadata.json, transcript.md, digest-request.md}."""

import argparse
import json
import sys
import tempfile
import unicodedata
from pathlib import Path

from . import YouTubeToNotesError, __version__
from .digest import render_digest_request_md
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
    validate_video_id,
)

OUTPUT_DIR = Path("output")
SOURCE_BY_KIND = {"manual": "manual_subtitles", "auto": "automatic_subtitles"}
TITLE_MAX_CHARS = 100
TITLE_FALLBACK = "video"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-to-notes",
        description="Получить воспроизводимый transcript из YouTube URL (subtitles first).",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="YouTube URL видео (не используется с --digest-request)",
    )
    parser.add_argument(
        "--digest-request",
        metavar="VIDEO_ID",
        default=None,
        help="Собрать digest-request.md из существующего output этого видео "
        "(каталог находится по metadata.json; локально, без сети)",
    )
    parser.add_argument(
        "--model",
        default="small",
        help="Модель faster-whisper для fallback (по умолчанию small, CPU int8)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать существующий output каталог",
    )
    parser.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        default=None,
        help="Читать cookies указанного браузера (напр. firefox) для доступа к YouTube; "
        "явный opt-in, без флага cookies не читаются",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.digest_request is not None:
        if args.url:
            parser.error("--digest-request работает с существующим output и не сочетается с URL")
        try:
            run_digest_request(args.digest_request, force=args.force)
        except YouTubeToNotesError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if not args.url:
        parser.error("требуется URL видео (или --digest-request VIDEO_ID)")
    try:
        video_id = extract_video_id(args.url)
    except YouTubeToNotesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        process(
            args.url,
            video_id,
            model=args.model,
            force=args.force,
            cookies_from_browser=args.cookies_from_browser,
        )
    except YouTubeToNotesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def sanitize_title(title: str) -> str:
    """Готовит title к роли component имени каталога: читаемо, deterministic, без path-опасных символов."""
    cleaned = "".join(ch for ch in title if unicodedata.category(ch)[0] != "C")
    cleaned = cleaned.replace("/", "-").replace("\\", "-")
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned[:TITLE_MAX_CHARS].rstrip()
    return cleaned or TITLE_FALLBACK


def output_dir_name(title: str, video_id: str) -> str:
    return f"{sanitize_title(title)}--{video_id}"


def find_output_dir(video_id: str) -> Path:
    """Ищет существующий output по metadata.json (не по имени каталога)."""
    matches = []
    if OUTPUT_DIR.is_dir():
        for child in sorted(OUTPUT_DIR.iterdir()):
            metadata_path = child / "metadata.json"
            if not child.is_dir() or not metadata_path.is_file():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(metadata, dict) and metadata.get("video_id") == video_id:
                matches.append(child)
    if not matches:
        raise YouTubeToNotesError(
            f"Output для video ID {video_id!r} не найден в {OUTPUT_DIR}: "
            "нет каталога с metadata.json, где video_id совпадает. "
            "Сначала запустите transcript pipeline для этого видео."
        )
    if len(matches) > 1:
        raise YouTubeToNotesError(
            f"Найдено несколько output для video ID {video_id!r}: "
            f"{', '.join(str(m) for m in matches)}. "
            "Устраните дубликаты, чтобы избежать выбора неправильного каталога."
        )
    return matches[0]


def process(
    url: str,
    video_id: str,
    model: str = "small",
    force: bool = False,
    cookies_from_browser: str | None = None,
) -> Path:
    video = fetch_metadata(url, cookies_from_browser)
    _log(f"Видео: {video.title!r} — {video.channel}")
    out_dir = OUTPUT_DIR / output_dir_name(video.title, video_id)
    _check_existing(out_dir, force)
    track = select_subtitle_track(video)
    whisper_model = None
    with tempfile.TemporaryDirectory(prefix="youtube-to-notes-") as tmp:
        tmp_path = Path(tmp)
        if track:
            source = SOURCE_BY_KIND[track.kind]
            language = track.language
            sub_path, sub_format = download_subtitles(url, track, tmp_path, cookies_from_browser)
            fragments = _parse_subtitles(sub_path, sub_format)
            _log(f"Субтитры: {source} [{track.key}], {len(fragments)} фрагментов")
        else:
            _log("Подходящие субтитры не найдены — Whisper fallback")
            audio_path = download_audio(url, tmp_path, cookies_from_browser)
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


def run_digest_request(video_id: str, force: bool = False) -> Path:
    """Собирает digest-request.md из существующего output (Milestone 2A)."""
    validate_video_id(video_id)
    out_dir = find_output_dir(video_id)
    transcript_path = out_dir / "transcript.md"
    if not transcript_path.exists():
        raise YouTubeToNotesError(f"Нет transcript.md в {out_dir}.")
    request_path = out_dir / "digest-request.md"
    if request_path.exists() and not force:
        raise YouTubeToNotesError(
            f"Output уже существует: {request_path}. Используйте --force для перезаписи."
        )
    try:
        metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise YouTubeToNotesError(f"Некорректный metadata.json в {out_dir}: {exc}") from exc
    transcript_md = transcript_path.read_text(encoding="utf-8")
    request_path.write_text(render_digest_request_md(metadata, transcript_md), encoding="utf-8")
    _log(f"Готово: {request_path}")
    return request_path


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
