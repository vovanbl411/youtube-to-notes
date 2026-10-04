"""Нормализация субтитров/сегментов и генерация transcript.md / metadata.json."""

import html
import json
import re
from collections import deque
from dataclasses import dataclass

MAX_SECTION_SPAN = 30.0  # сек; секция длиннее разбивается
SECTION_GAP = 3.5  # сек; пауза больше — новая секция
RECENT_LINES = 8  # окно дедупликации перекрывающихся строк автосубтитров

TRANSCRIPT_SOURCES = ("manual_subtitles", "automatic_subtitles", "whisper")

_TAG_RE = re.compile(r"<[^>]+>")
_INVISIBLE_RE = re.compile("[​‎‏﻿]")


@dataclass(frozen=True)
class Fragment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Section:
    start: float
    text: str


def fragments_from_json3(data: dict) -> list[Fragment]:
    raw = []
    for event in data.get("events") or []:
        segs = event.get("segs")
        if not segs:
            continue
        text = _clean_text("".join(seg.get("utf8", "") for seg in segs))
        if not text:
            continue
        start = event.get("tStartMs", 0) / 1000.0
        duration = event.get("dDurationMs", 0) / 1000.0
        raw.append(Fragment(start, start + duration, text))
    return _drop_duplicates(raw)


def fragments_from_vtt(content: str) -> list[Fragment]:
    raw = []
    for block in re.split(r"\n\s*\n", content):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        timing_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing_idx is None:
            continue  # заголовок WEBVTT, NOTE, cue-идентификаторы без таймингов и т.п.
        timing = lines[timing_idx]
        start = _parse_timestamp(timing.split("-->")[0])
        end = _parse_timestamp(timing.split("-->")[1].split()[0])
        text = _clean_text(" ".join(lines[timing_idx + 1 :]))
        if text:
            raw.append(Fragment(start, end, text))
    return _drop_duplicates(raw)


def group_sections(
    fragments: list[Fragment],
    max_span: float = MAX_SECTION_SPAN,
    gap: float = SECTION_GAP,
) -> list[Section]:
    """Группирует фрагменты в секции: по паузе больше gap или длине секции больше max_span."""
    sections = []
    start = end = None
    lines: list[str] = []
    for frag in fragments:
        if start is None:
            start, end, lines = frag.start, frag.end, [frag.text]
        elif frag.start - end > gap or frag.end - start >= max_span:
            sections.append(Section(start, " ".join(lines)))
            start, end, lines = frag.start, frag.end, [frag.text]
        else:
            lines.append(frag.text)
            end = max(end, frag.end)
    if start is not None:
        sections.append(Section(start, " ".join(lines)))
    return sections


def format_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def render_transcript_md(video, language: str, source: str, sections: list[Section]) -> str:
    lines = [
        "---",
        f"source: {video.url}",
        f"video_id: {video.video_id}",
        f"title: {json.dumps(video.title, ensure_ascii=False)}",
        f"channel: {json.dumps(video.channel, ensure_ascii=False)}",
        f"language: {language}",
        f"transcript_source: {source}",
        "---",
        "",
        "# Transcript",
        "",
    ]
    for section in sections:
        lines += [f"## {format_timestamp(section.start)}", "", section.text, ""]
    return "\n".join(lines).rstrip() + "\n"


def render_metadata_json(
    video, language: str, source: str, whisper_model: str | None = None
) -> str:
    data = {
        "url": video.url,
        "video_id": video.video_id,
        "title": video.title,
        "channel": video.channel,
        "upload_date": _iso_date(video.upload_date),
        "duration": video.duration,
        "language": language,
        "transcript_source": source,
    }
    if whisper_model:
        data["whisper_model"] = whisper_model
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _clean_text(text: str) -> str:
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _INVISIBLE_RE.sub("", text)
    return " ".join(text.split())


def _drop_duplicates(fragments: list[Fragment]) -> list[Fragment]:
    """Убирает повторяющиеся строки перекрывающихся cues автосубтитров."""
    recent = deque(maxlen=RECENT_LINES)
    unique = []
    for frag in fragments:
        if frag.text in recent:
            continue
        recent.append(frag.text)
        unique.append(frag)
    return unique


def _parse_timestamp(value: str) -> float:
    parts = value.strip().split(":")
    seconds = float(parts[-1])
    if len(parts) >= 2:
        seconds += int(parts[-2]) * 60
    if len(parts) >= 3:
        seconds += int(parts[0]) * 3600
    return seconds


def _iso_date(raw: str | None) -> str | None:
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
