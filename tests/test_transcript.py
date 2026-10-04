import json

from youtube_to_notes.transcript import (
    Fragment,
    format_timestamp,
    fragments_from_json3,
    fragments_from_vtt,
    group_sections,
    render_metadata_json,
    render_transcript_md,
)
from youtube_to_notes.youtube import Video

JSON3 = {
    "events": [
        {"tStartMs": 0, "segs": []},
        {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Привет"}]},
        {"tStartMs": 2000, "dDurationMs": 2000, "segs": [{"utf8": "мир​"}]},
        {"tStartMs": 4000, "dDurationMs": 2000, "segs": [{"utf8": "Привет"}]},
    ]
}

VTT = """WEBVTT
Kind: captions
Language: ru

cue-identifier
00:00:00.000 --> 00:00:02.000 align:start position:0%
привет <c.colorE5E5E5>мир</c>

00:00:02.000 --> 00:00:04.000 line:0%
вторая&nbsp;строка

NOTE это комментарий

00:00:04.000 --> 00:00:06.000
третья
"""


def make_video():
    return Video(
        video_id="abc12345678",
        url="https://youtu.be/abc12345678",
        title='Он сказал: "привет"',
        channel="Channel & Co",
        upload_date="20240102",
        duration=61.5,
        language="ru",
    )


def test_json3_strips_markers_and_dedupes():
    fragments = fragments_from_json3(JSON3)
    assert [f.text for f in fragments] == ["Привет", "мир"]
    assert fragments[0].start == 0.0
    assert fragments[0].end == 2.0


def test_vtt_strips_headers_tags_and_entities():
    fragments = fragments_from_vtt(VTT)
    assert [f.text for f in fragments] == ["привет мир", "вторая строка", "третья"]
    assert fragments[1].start == 2.0
    assert fragments[1].end == 4.0


def test_format_timestamp():
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(61.4) == "01:01"
    assert format_timestamp(3599) == "59:59"
    assert format_timestamp(3600) == "1:00:00"
    assert format_timestamp(3661.6) == "1:01:02"


def test_group_sections_by_gap():
    fragments = [
        Fragment(0, 2, "a"),
        Fragment(3, 5, "b"),
        Fragment(10, 12, "c"),  # пауза 5c > 3.5c -> новая секция
    ]
    sections = group_sections(fragments)
    assert [(s.start, s.text) for s in sections] == [(0, "a b"), (10, "c")]


def test_group_sections_by_span():
    fragments = [Fragment(i * 10, i * 10 + 5, f"t{i}") for i in range(5)]
    sections = group_sections(fragments, max_span=30.0, gap=100.0)
    assert len(sections) == 2
    assert sections[0].text == "t0 t1 t2"
    assert sections[1].start == 30.0


def test_transcript_md_format():
    sections = group_sections([Fragment(0, 2, "Первый фрагмент."), Fragment(42, 50, "Второй.")])
    md = render_transcript_md(make_video(), "ru", "manual_subtitles", sections)
    lines = md.splitlines()
    assert lines[0] == "---"
    assert "source: https://youtu.be/abc12345678" in lines
    assert "video_id: abc12345678" in lines
    assert f'title: {json.dumps(make_video().title, ensure_ascii=False)}' in lines
    assert "language: ru" in lines
    assert "transcript_source: manual_subtitles" in lines
    assert "# Transcript" in lines
    assert "## 00:00" in lines
    assert "## 00:42" in lines
    assert "Первый фрагмент." in lines


def test_metadata_json_fields():
    raw = render_metadata_json(make_video(), "ru", "manual_subtitles")
    data = json.loads(raw)
    assert data["upload_date"] == "2024-01-02"
    assert data["duration"] == 61.5
    assert data["transcript_source"] == "manual_subtitles"
    assert "whisper_model" not in data


def test_metadata_json_whisper_source():
    data = json.loads(
        render_metadata_json(make_video(), "en", "whisper", whisper_model="small")
    )
    assert data["transcript_source"] == "whisper"
    assert data["whisper_model"] == "small"
    assert data["language"] == "en"


def test_metadata_json_missing_optional_fields():
    video = Video("x" * 11, "u", "t", "c", None, None, None)
    data = json.loads(render_metadata_json(video, "ru", "automatic_subtitles"))
    assert data["upload_date"] is None
    assert data["duration"] is None
