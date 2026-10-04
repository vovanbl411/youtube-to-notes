# youtube-to-notes

Простой pipeline для превращения YouTube-видео в проверяемый материал для работы
с базой знаний:

```text
YouTube → transcript → digest request → structured digest → Obsidian proposal → human review
```

Сейчас работают первые два шага цепочки: воспроизводимый transcript и self-contained
digest request. Остальное — направление развития (см. «Что уже работает и куда
идёт» ниже).

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/youtube-to-notes 'https://youtu.be/VIDEO_ID'
```

Опции:

- `--digest-request VIDEO_ID` — собрать digest-request для уже обработанного видео
  (следующий раздел);
- `--model MODEL` — модель faster-whisper для fallback (по умолчанию `small`; для
  быстрых проверок `base`/`tiny`);
- `--force` — перезаписать существующий output;
- `--cookies-from-browser BROWSER` — читать cookies указанного браузера (например,
  `firefox`) для доступа к YouTube. Явный opt-in: без флага cookies не читаются.

Нужен доступ в интернет (YouTube; при первом Whisper-запуске — модель ~0.5 ГБ с
HuggingFace). Прочие требования — в разделе «Детали».

## Что получится

```text
output/
└── Название видео--VIDEO_ID/
    ├── metadata.json
    └── transcript.md
```

- `metadata.json` — provenance: URL, video ID, title, канал, дата загрузки,
  длительность, язык, источник transcript (субтитры или Whisper).
- `transcript.md` — текст видео, разбитый на секции с таймкодами.

Имя каталога человекочитаемо: `<sanitized-title>--<video-id>`, например
`output/Подстановка данных из Secret в конфиги приложений.--D3csT2KvOS4/`. Title
очищается минимально — `/` и `\` заменяются на `-`, control-символы удаляются,
повторяющиеся пробелы схлопываются, длина ограничена 100 символами; Unicode и
пунктуация сохраняются. `video_id` остаётся identity/provenance. Каталоги
`output/<video-id>/` из старых версий остаются совместимыми и не переименовываются
автоматически.

## Дальше: digest request

Второй работающий шаг — handoff для создания structured digest:

```bash
.venv/bin/youtube-to-notes --digest-request VIDEO_ID
```

```text
metadata.json + transcript.md
        ↓
digest-request.md
        ↓
ChatGPT / agent / human
        ↓
digest.md
```

Команда принимает только `video_id`; соответствующий каталог (независимо от того,
назван ли он по новому контракту или по-старому — `output/<video-id>/`) ищется по
`video_id` в `metadata.json` непосредственных подкаталогов `output/`, а не по имени
каталога. Если подходящих каталогов несколько (после ручных rename/copy) — CLI
отказывается выбирать и перечисляет их.

`digest-request.md` собирается из локальных `metadata.json` и `transcript.md`: без
сети, без повторного извлечения данных с YouTube и без Whisper. Файл полностью
self-contained: содержит инструкцию (task), digest contract v1 (структуру будущего
`digest.md`), source metadata и полный transcript — его можно как есть передать
человеку, агенту/Codex или загрузить в ChatGPT UI, ничего больше не прикладывая.

Генерация детерминирована: при одинаковых входных файлах результат байт-в-байт
воспроизводим. Существующий `digest-request.md` не перезаписывается молча — нужен
явный `--force`.

## Что уже работает и куда идёт

**Работает:**

- YouTube URL → воспроизводимый transcript (subtitles first, Whisper fallback);
- `digest-request.md` — self-contained задача на digest для человека, агента или LLM.

**Куда идёт (ещё не реализовано):**

- `digest.md` — его создаёт исполнитель digest-request по контракту; автоматической
  генерации внутри приложения нет;
- chunking длинных transcript: digest-request сейчас всегда содержит полный
  transcript;
- Obsidian-aware proposal и human review — интеграции с vault нет.

Сторонней инфраструктуры тоже нет: LLM API и ключей, batch processing,
daemon/watch mode, web UI, Docker, баз данных и очередей.

## Как устроен pipeline

```text
YouTube URL
    ├── подходящие subtitles доступны → скачать → normalize ──┐
    └── subtitles отсутствуют → audio-only → faster-whisper ──┤
                                                             ↓
                                              metadata.json + transcript.md
```

Приоритет источника: ручные субтитры → автоматические → Whisper. Если подходящие
субтитры найдены, аудио не скачивается и Whisper не запускается.

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

### Whisper fallback

Только когда подходящих субтитров нет:

1. Скачивается `bestaudio` (без перекодирования).
2. `faster-whisper`, CPU, `int8` (модель по умолчанию `small`, `vad_filter=True`).
3. Язык определяется автоматически и попадает в `metadata.json`.

Whisper на CPU медленный: на модели `small` ориентируйтесь на порядок реального
времени (зависит от процессора).

### Повторные запуски и --force

Output детерминирован: фиксированные имена файлов, никаких случайных имён.
Повторный запуск сначала ищет существующий output по `video_id` (в `metadata.json`)
и переиспользует его как есть — даже если каталог назван по-старому (`<video-id>/`)
или title видео успел измениться; rename при этом не делается, второй каталог не
создаётся. Если `metadata.json` или `transcript.md` уже существуют, запуск
завершается ошибкой (защита от потери ручных правок); `--force` перезаписывает.

## Детали

### Требования

- Python >= 3.10 (проверено на 3.14).
- JavaScript runtime — актуальный YouTube-экстрактор yt-dlp (extra `default`) решает
  JS-челленджи YouTube через внешний JS runtime; предпочтительный вариант — Deno
  (исполняемый файл `deno` в `PATH`). Без него извлечение данных с YouTube может не
  работать.
- ffmpeg не требуется (аудио декодируется через PyAV внутри faster-whisper).

### metadata.json

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

### transcript.md

YAML frontmatter (provenance: URL, video ID, title, channel, язык, источник) + текст,
разбитый на секции `## MM:SS` (или `## H:MM:SS` для длинных видео):

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

## Ограничения

- Русский и английский пути покрыты unit-тестами. Реально проверены оба
  runtime-пути: automatic subtitles → PASS; видео без subtitles → audio download →
  Whisper `small` → PASS.
- Если у видео нет трека на языке оригинала, может быть выбран автоперевод на `ru`/`en` —
  качество машинного перевода не оценивается.
- Возрастные/приватные видео без cookies недоступны (ошибка yt-dlp передаётся как есть).
- YouTube может блокировать запросы без cookies («Sign in to confirm you're not a bot») —
  в зависимости от IP и конкретного видео; в этом случае используйте
  `--cookies-from-browser BROWSER` (например, `firefox`).
- Дедупликация строк — по точному совпадению в скользящем окне из 8 строк; легитимно
  повторившаяся реплика внутри окна тоже будет отброшена.

## Тесты

```bash
.venv/bin/pip install -e .[dev]
.venv/bin/python -m pytest
```

Unit-тесты не ходят в сеть; реальные smoke-тесты (subtitles path и Whisper fallback)
выполняются вручную на реальных видео.
