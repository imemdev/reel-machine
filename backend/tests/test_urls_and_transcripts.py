from __future__ import annotations

import json

import pytest

from backend.app.transcripts import Segment, parse_whisper_json, to_srt, to_vtt
from backend.app.urls import URLValidationError, canonicalize_url


def test_canonicalizes_supported_social_urls_and_removes_tracking() -> None:
    instagram = canonicalize_url("https://www.instagram.com/reel/ABC_123/?igsh=ignored&utm_source=x")
    assert instagram.platform == "instagram"
    assert instagram.canonical_id == "ABC_123"
    assert instagram.source_url == "https://www.instagram.com/reel/ABC_123"

    facebook = canonicalize_url("https://www.facebook.com/watch/?v=456&si=ignored")
    assert facebook.platform == "facebook"
    assert facebook.canonical_id == "456"

    tiktok = canonicalize_url("https://www.tiktok.com/@creator/video/789")
    assert tiktok.platform == "tiktok"
    assert tiktok.canonical_id == "789"


def test_rejects_fixture_when_disabled_and_accepts_it_for_local_tests() -> None:
    with pytest.raises(URLValidationError, match="Fixture sources are disabled"):
        canonicalize_url("fixture://tunisian-demo")
    fixture = canonicalize_url("fixture://tunisian-demo", allow_fixture=True)
    assert fixture.platform == "fixture"
    assert fixture.canonical_url == "fixture://tunisian-demo"


def test_export_timestamps_keep_full_millisecond_precision(tmp_path) -> None:
    segments = [Segment(1_234, 5_678, "مرحبا programme")]
    assert "00:00:01,234 --> 00:00:05,678" in to_srt(segments)
    assert "00:00:01.234 --> 00:00:05.678" in to_vtt(segments)

    raw = tmp_path / "whisper.json"
    raw.write_text(json.dumps({"transcription": [{"offsets": {"from": 1234, "to": 5678}, "text": "hello"}]}), encoding="utf-8")
    assert parse_whisper_json(raw) == [Segment(1234, 5678, "hello")]
