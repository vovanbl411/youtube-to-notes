"""Доступ к YouTube через yt-dlp: метаданные, выбор и загрузка субтитров, загрузка аудио."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.cookies import SUPPORTED_BROWSERS
from yt_dlp.utils import DownloadError

from . import YouTubeToNotesError

PREFERRED_LANGUAGES = ("ru", "en")

VIDEO_ID_RE = re.compile(
    r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/|/v/)"
    r"([0-9A-Za-z_-]{11})(?![0-9A-Za-z_-])"
)

ALLOWED_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtube-nocookie.com",  # официальный host /embed/ ссылок
    }
)


def extract_video_id(url: str) -> str:
    url = url.strip()
    try:
        host = urlsplit(url).hostname
    except ValueError as exc:
        raise YouTubeToNotesError(f"Некорректный URL: {url!r}") from exc
    if (host or "").lower() not in ALLOWED_HOSTS:
        raise YouTubeToNotesError(
            f"Не YouTube URL: {url!r}. Ожидается ссылка на youtube.com или youtu.be"
        )
    match = VIDEO_ID_RE.search(url)
    if not match:
        raise YouTubeToNotesError(
            f"Не удалось извлечь video ID из URL: {url!r}. Ожидается ссылка вида "
            "'https://www.youtube.com/watch?v=VIDEO_ID' или 'https://youtu.be/VIDEO_ID'"
        )
    return match.group(1)


@dataclass
class Video:
    video_id: str
    url: str
    title: str
    channel: str
    upload_date: str | None
    duration: float | None
    language: str | None
    subtitles: dict = field(default_factory=dict)
    automatic_captions: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SubtitleTrack:
    kind: str  # "manual" | "auto"
    key: str  # точный ключ yt-dlp, например "ru" или "en-orig"
    language: str  # базовый код языка, например "ru"


def _ydl_opts(cookies_from_browser: str | None = None, **extra):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
    }
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = _browser_cookie_spec(cookies_from_browser)
    return {**opts, **extra}


def _browser_cookie_spec(browser: str) -> tuple:
    name = browser.strip().lower()
    if name not in SUPPORTED_BROWSERS:
        raise YouTubeToNotesError(
            f"Неподдерживаемый браузер для --cookies-from-browser: {browser!r}. "
            f"Поддерживаются: {', '.join(sorted(SUPPORTED_BROWSERS))}"
        )
    return (name, None, None, None)


def fetch_metadata(url: str, cookies_from_browser: str | None = None) -> Video:
    try:
        with YoutubeDL(_ydl_opts(cookies_from_browser, skip_download=True)) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise YouTubeToNotesError(f"yt-dlp не смог получить данные видео: {exc}") from exc
    if not info:
        raise YouTubeToNotesError(f"yt-dlp не вернул данные для {url}")
    return Video(
        video_id=info.get("id") or "",
        url=info.get("webpage_url") or url,
        title=info.get("title") or "",
        channel=info.get("channel") or info.get("uploader") or "",
        upload_date=info.get("upload_date") or None,
        duration=float(info["duration"]) if info.get("duration") else None,
        language=info.get("language") or None,
        subtitles=info.get("subtitles") or {},
        automatic_captions=info.get("automatic_captions") or {},
    )


def select_subtitle_track(video: Video) -> SubtitleTrack | None:
    """Простой детерминированный выбор трека субтитров.

    Приоритет: ручные субтитры > автоматические; внутри одного типа язык:
    язык оригинала видео > ru > en > любой другой (по алфавиту ключей).
    """
    original_base = None
    original = video.language or _detect_original(video.automatic_captions)
    if original:
        original_base = _base_language(original)
    candidates = []
    for kind, tracks in (("manual", video.subtitles), ("auto", video.automatic_captions)):
        for key, formats in tracks.items():
            if not formats or key == "live_chat":
                continue
            base = _base_language(key)
            if original_base and base == original_base:
                lang_rank = 0
            elif base in PREFERRED_LANGUAGES:
                lang_rank = PREFERRED_LANGUAGES.index(base) + 1
            else:
                lang_rank = len(PREFERRED_LANGUAGES) + 1
            candidates.append((0 if kind == "manual" else 1, lang_rank, len(key), key, kind, base))
    if not candidates:
        return None
    _, _, _, key, kind, base = min(candidates)
    return SubtitleTrack(kind, key, base)


def download_subtitles(
    url: str, track: SubtitleTrack, dest_dir: Path, cookies_from_browser: str | None = None
) -> tuple[Path, str]:
    """Скачивает выбранный трек (формат json3, при отсутствии vtt).

    Возвращает (путь к файлу, формат "json3" | "vtt").
    """
    opts = _ydl_opts(
        cookies_from_browser,
        skip_download=True,
        writesubtitles=track.kind == "manual",
        writeautomaticsub=track.kind == "auto",
        subtitleslangs=[track.key],
        subtitlesformat="json3/vtt",
        outtmpl=str(dest_dir / "subs.%(ext)s"),
    )
    try:
        with YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except DownloadError as exc:
        raise YouTubeToNotesError(f"yt-dlp не смог скачать субтитры ({track.key}): {exc}") from exc
    files = sorted(dest_dir.glob("subs.*"))
    if not files:
        raise YouTubeToNotesError(f"yt-dlp не создал файл субтитров для трека {track.key}")
    path = files[0]
    return path, path.suffix.lstrip(".")


def download_audio(url: str, dest_dir: Path, cookies_from_browser: str | None = None) -> Path:
    opts = _ydl_opts(
        cookies_from_browser,
        format="bestaudio/best",
        outtmpl=str(dest_dir / "audio.%(ext)s"),
    )
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
    except DownloadError as exc:
        raise YouTubeToNotesError(f"yt-dlp не смог скачать аудио: {exc}") from exc
    if not path.exists():
        files = sorted(dest_dir.glob("audio.*"))
        if not files:
            raise YouTubeToNotesError("yt-dlp не создал файл аудио")
        path = files[0]
    return path


def _base_language(key: str) -> str:
    return key.split("-")[0].lower()


def _detect_original(automatic_captions: dict) -> str | None:
    for key in automatic_captions:
        if key.endswith("-orig"):
            return key[: -len("-orig")]
    return None
