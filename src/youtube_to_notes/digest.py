"""Milestone 2A: deterministic digest-request.md из metadata.json + transcript.md."""

import json

from .transcript import format_timestamp


def render_digest_request_md(metadata: dict, transcript_md: str) -> str:
    """Собирает self-contained digest-request.md. Только локальные данные, без сети."""
    url = metadata["url"]
    video_id = metadata["video_id"]
    title = metadata["title"]
    channel = metadata["channel"]
    upload_date = metadata["upload_date"]
    duration = metadata["duration"]
    language = metadata["language"]
    source = metadata["transcript_source"]
    whisper_model = metadata.get("whisper_model")

    duration_str = "null" if duration is None else f"{format_timestamp(duration)} ({duration:g} с)"
    upload_date_str = upload_date if upload_date is not None else "null"

    contract = f"""---
source: {url}
video_id: {video_id}
title: {json.dumps(title, ensure_ascii=False)}
channel: {json.dumps(channel, ensure_ascii=False)}
language: {language}
transcript_source: {source}
---

# Digest

## Основная идея

Краткое самостоятельное описание темы и основной ценности материала.

## Ключевые знания

### Название фрагмента знания

Самостоятельное объяснение идеи своими словами.

**Практика:** применение, если оно действительно следует из источника.

**Источник:** [MM:SS](https://youtu.be/{video_id}?t=SECONDS)

## Практическое применение

Конкретные действия, методы, команды, подходы или решения, действительно поддержанные источником.

## Требует проверки

Сомнительные термины или технические утверждения с причиной сомнения и timestamp.

Если таких моментов нет, напишите: `Нет.`

## Темы и связи

Список канонических технических тем/понятий.

Не использовать здесь Obsidian wiki-links."""

    lines = [
        "# Structured Digest Request",
        "",
        "## Task",
        "",
        "Создайте структурированный digest видео по контракту ниже. Transcript — единственный evidence: итоговый digest должен быть полезен сам по себе, даже без просмотра видео. Результат сохраните как `digest.md`.",
        "",
        "## Required output",
        "",
        "Digest contract v1 — точная структура (frontmatter уже заполнен):",
        "",
        "```markdown",
        contract,
        "```",
        "",
        "## Analysis rules",
        "",
        "- Transcript является evidence: не пересказывайте его по порядку, выделяйте standalone knowledge fragments — самостоятельные единицы знания.",
        "- Используйте только содержание, поддержанное источником; не выдумывайте отсутствующие факты.",
        "- Очевидные transcription errors в технических терминах можно исправлять.",
        "- Если correction неоднозначна — не угадывайте, а помещайте термин в раздел «Требует проверки».",
        "- Спорные технические утверждения также помещайте в «Требует проверки» с причиной сомнения и timestamp.",
        "- Timestamps используйте для существенных knowledge fragments; timestamp не требуется для каждого предложения — один или несколько timestamps могут подтверждать целый фрагмент.",
        f"- Timestamp — кликабельная ссылка вида `https://youtu.be/{video_id}?t=SECONDS`. Пример: [12:41](https://youtu.be/{video_id}?t=761).",
        "- Секции transcript озаглавлены `MM:SS` или `H:MM:SS`; для ссылки переводите время в секунды от начала видео.",
        "",
        "## Source metadata",
        "",
        f"- URL: {url}",
        f"- Video ID: {video_id}",
        f"- Title: {title}",
        f"- Channel: {channel}",
        f"- Upload date: {upload_date_str}",
        f"- Duration: {duration_str}",
        f"- Language: {language}",
        f"- Transcript source: {source}",
    ]
    if whisper_model:
        lines.append(f"- Whisper model: {whisper_model}")
    lines += [
        "",
        "## Transcript",
        "",
        transcript_md.rstrip("\n"),
        "",
    ]
    return "\n".join(lines)
