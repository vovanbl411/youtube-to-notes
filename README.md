# youtube-to-notes

Milestone 1: получение воспроизводимого transcript из YouTube URL.

```text
youtube-to-notes 'https://www.youtube.com/watch?v=VIDEO_ID'
```

создаёт:

```text
output/
└── VIDEO_ID/
    ├── metadata.json
    └── transcript.md
```

Дальнейшая цель проекта (knowledge extraction, Obsidian) — вне рамок текущего MVP.

## Что этот MVP НЕ делает

- Никакой LLM / ChatGPT / Codex интеграции.
- Никакой Obsidian интеграции, изменения vault, поиска заметок.
- Нет `digest.md`, batch processing, daemon/watch mode, scheduler, web UI.
- Нет Docker, базы данных, очереди задач, configuration framework.

## Requirements

- Python >= 3.10
- JavaScript runtime — актуальный YouTube-экстрактор yt-dlp (extra `default`) решает
  JS-челленджи YouTube через внешний JS runtime; предпочтительный вариант — Deno
  (исполняемый файл `deno` в `PATH`). Без него извлечение данных с YouTube может не работать.
- Доступ в интернет (YouTube; при первом Whisper-запуске — модель ~0.5 ГБ с HuggingFace в `~/.cache`)
- ffmpeg не требуется (аудио декодируется через PyAV внутри faster-whisper)

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e .          # только runtime
.venv/bin/pip install -e .[dev]     # + pytest
```

## Пример запуска

```bash
.venv/bin/youtube-to-notes 'https://www.youtube.com/watch?v=VIDEO_ID'
```

Опции:

- `--digest-request VIDEO_ID` — собрать `output/<VIDEO_ID>/digest-request.md` из уже
  существующих `metadata.json` и `transcript.md` (см. ниже).
- `--model MODEL` — модель faster-whisper для fallback (по умолчанию `small`; для быстрых
  проверок `base`/`tiny`).
- `--force` — перезаписать существующий `output/<video-id>/`.
- `--cookies-from-browser BROWSER` — читать cookies указанного браузера (например,
  `firefox`) для доступа к YouTube. Нужен, когда YouTube требует browser session и
  отвечает ошибкой «Sign in to confirm you're not a bot». Это явный opt-in: без флага
  приложение не читает cookies браузера.

```bash
.venv/bin/youtube-to-notes \
  --cookies-from-browser firefox \
  'https://www.youtube.com/watch?v=VIDEO_ID'
```

## Формат output

`metadata.json`:

```json
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "video_id": "VIDEO_ID",
  "title": "Example",
  "channel": "Example Channel",
  "upload_date": "2024-01-02",
  "duration": 123.0,
  "language": "ru",
  "transcript_source": "manual_subtitles"
}
```

- `upload_date` / `duration` — `null`, если недоступны.
- `transcript_source` — одно из: `manual_subtitles`, `automatic_subtitles`, `whisper`.
- При Whisper в `metadata.json` добавляется `whisper_model`.
- Сырой ответ yt-dlp не сохраняется.

`transcript.md` — YAML frontmatter (provenance: URL, video ID, title, channel, язык,
источник) + текст, разбитый на секции `## MM:SS` (или `## H:MM:SS` для длинных видео):

```markdown
---
source: https://youtu.be/VIDEO_ID
video_id: VIDEO_ID
title: "Example"
channel: "Example Channel"
language: ru
transcript_source: manual_subtitles
---

# Transcript

## 00:00

Текст первого фрагмента.

## 00:42

Следующий фрагмент.
```

## digest-request.md (Milestone 2A)

Для видео, transcript которого уже получен, можно собрать handoff-задачу для создания
structured digest:

```bash
.venv/bin/youtube-to-notes --digest-request VIDEO_ID
```

Создаёт `output/<video-id>/digest-request.md` из локальных `metadata.json` и
`transcript.md`: без сети, без повторного извлечения данных с YouTube и без Whisper.
Файл полностью self-contained: содержит инструкцию (task), digest contract v1
(структуру будущего `digest.md`), source metadata и полный transcript — его можно
как есть передать человеку, агенту/Codex или загрузить в ChatGPT UI, ничего больше
не прикладывая.

Генерация детерминирована: при одинаковых входных файлах результат байт-в-байт
воспроизводим. Существующий `digest-request.md` не перезаписывается молча — как и в
transcript pipeline, нужен явный `--force`.

Ограничения: автоматической генерации `digest.md` внутри приложения нет — итоговый
digest создаёт исполнитель запроса по контракту; chunking длинных transcript пока не
реализован (request всегда содержит полный transcript).

## Pipeline: subtitles first

```text
YouTube URL
    ├── подходящие subtitles доступны → скачать → normalize ──┐
    └── subtitles отсутствуют → audio-only → faster-whisper ──┤
                                                             ↓
                                              metadata.json + transcript.md
```

Если подходящие субтитры найдены, аудио не скачивается и Whisper не запускается.

### Алгоритм выбора субтитров

Простой и детерминированный:

1. Ручные субтитры всегда приоритетнее автоматических.
2. Внутри одного типа язык выбирается так: язык оригинала видео → `ru` → `en` →
   любой другой (при равенстве — по алфавиту ключей).
3. Язык оригинала берётся из метаданных видео; если он не указан — из ключа
   `...-orig` в списке автосубтитров.
4. `live_chat` субтитрами не считается.

### Нормализация

Из субтитров убирается технический мусор: заголовки WEBVTT, cue-идентификаторы,
inline-теги и стили, позиционирование, HTML-entities, невидимые символы, повторяющиеся
строки перекрывающихся cues автосубтитров. Оригинальные тайминги сохраняются; cues не
сохраняются один-к-одному — фрагменты группируются в секции по паузе (> 3.5 c) или
длине секции (>= 30 c).

## Whisper fallback

Только когда подходящих субтитров нет:

1. Скачивается `bestaudio` (без перекодирования).
2. `faster-whisper`, CPU, `int8` (модель по умолчанию `small`, `vad_filter=True`).
3. Язык определяется автоматически и попадает в `metadata.json`.

## Повторный запуск

Output детерминирован: всегда `output/<video-id>/` с фиксированными именами файлов,
никаких случайных имён. Если `metadata.json` или `transcript.md` уже существуют,
запуск завершается ошибкой (защита от потери ручных правок); `--force` перезаписывает.

## Текущие ограничения

- Проверен на Python 3.14; русский и английский пути покрыты unit-тестами,
  реальный smoke-запуск выполнен на английском видео с ручными субтитрами.
- Если у видео нет трека на языке оригинала, может быть выбран автоперевод на `ru`/`en` —
  качество машинного перевода не оценивается.
- Whisper на CPU медленный: на модели `small` ориентируйтесь на порядок реального
  времени (зависит от процессора).
- Возрастные/приватные видео без cookies недоступны (ошибка yt-dlp передаётся как есть).
- YouTube может блокировать запросы без cookies («Sign in to confirm you're not a bot») —
  в зависимости от IP и конкретного видео; в этом случае используйте
  `--cookies-from-browser BROWSER` (например, `firefox`).
- Дедупликация строк — по точному совпадению в скользящем окне из 8 строк; легитимно
  повторившаяся реплика внутри окна тоже будет отброшена.

## Тесты

```bash
.venv/bin/python -m pytest
```

Unit-тесты не ходят в сеть; реальные smoke-тесты (subtitles path и Whisper fallback)
выполняются вручную на реальных видео.
