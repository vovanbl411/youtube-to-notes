"""Whisper fallback: транскрибация аудио через faster-whisper (CPU, int8)."""

from pathlib import Path

from . import YouTubeToNotesError
from .transcript import Fragment


def transcribe_audio(audio_path: Path, model_size: str = "small") -> tuple[list[Fragment], str]:
    """Возвращает (фрагменты, определённый язык)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise YouTubeToNotesError(
            "Библиотека faster-whisper не установлена (pip install faster-whisper)"
        ) from exc
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(audio_path), vad_filter=True)
        fragments = [
            Fragment(seg.start, seg.end, seg.text.strip())
            for seg in segments
            if seg.text.strip()
        ]
    except Exception as exc:
        raise YouTubeToNotesError(f"Whisper не смог транскрибировать аудио: {exc}") from exc
    return fragments, (info.language or "")
