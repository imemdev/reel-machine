from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import media
from backend.app.main import create_app
from backend.app.pipeline import Segment
from backend.app.urls import URLValidationError, canonicalize_url

FFMPEG = shutil.which("ffmpeg")


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&t=42s",
    "https://youtu.be/dQw4w9WgXcQ?si=tracking",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share",
    "https://www.youtube.com/live/dQw4w9WgXcQ",
    "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
])
def test_youtube_urls_share_one_identity(url) -> None:
    identity = canonicalize_url(url)
    assert identity.platform == "youtube"
    assert identity.canonical_id == "dQw4w9WgXcQ"
    assert identity.source_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/playlist?list=PL123",
    "https://www.youtube.com/watch?v=short",
])
def test_youtube_channels_and_playlists_are_rejected(url) -> None:
    with pytest.raises(URLValidationError):
        canonicalize_url(url)


def test_media_names_are_readable_and_safe() -> None:
    video = {"saved_at": "2026-09-24T10:00:00+00:00", "display_title": 'كسكسي: "جدتي" / part 1?', "canonical_id": "abc:123", "platform": "youtube"}
    name = media.media_basename(video)
    assert name.startswith("2026-09-24 كسكسي")
    assert not any(char in name for char in '<>:"/\\|?*')
    assert name.endswith("[abc 123]")
    assert len(media.safe_name("x" * 500)) <= 71


def test_export_places_matching_video_and_audio(tmp_path) -> None:
    source_video = tmp_path / "work" / "source.mp4"
    source_audio = tmp_path / "work" / "audio.wav"
    source_video.parent.mkdir()
    source_video.write_bytes(b"video-bytes")
    source_audio.write_bytes(b"audio-bytes")
    video = {"saved_at": "2026-09-24", "display_title": "Hello", "canonical_id": "id1", "platform": "youtube"}
    exported = media.export_media(tmp_path / "Media", video, video_file=source_video, audio_file=source_audio)
    assert exported["video"] == tmp_path / "Media" / "Videos" / "YouTube" / "2026-09-24 Hello [id1].mp4"
    assert exported["audio"] == tmp_path / "Media" / "Audio" / "YouTube" / "2026-09-24 Hello [id1].wav"
    source_video.unlink()  # working copies can be cleaned up; the media folder keeps its files
    assert exported["video"].read_bytes() == b"video-bytes"
    # Exporting again is a no-op.
    assert media.export_media(tmp_path / "Media", video, video_file=None, audio_file=source_audio)["audio"] == exported["audio"]


def test_video_download_command_downloads_video_not_audio(tmp_path) -> None:
    command = media.video_download_command(ytdlp="yt-dlp", ffmpeg="/usr/bin/ffmpeg",
                                           source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", output=tmp_path / "source.%(ext)s")
    assert "--extract-audio" not in command
    assert command[command.index("--merge-output-format") + 1] == "mp4"
    assert command[command.index("--ffmpeg-location") + 1] == "/usr/bin/ffmpeg"
    assert command[-1] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is required for the end-to-end media test")
def test_youtube_video_flows_into_the_media_folder(runtime, monkeypatch) -> None:
    def fake_download(*, ytdlp, ffmpeg, source_url, output):
        target = str(output).replace("%(ext)s", "mp4")
        return [FFMPEG, "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", target]

    monkeypatch.setattr(media, "video_download_command", fake_download)
    monkeypatch.setattr(type(runtime.runner), "_transcribe_farukstt",
                        lambda self, audio_path, raw_path: (raw_path.write_text("{}", encoding="utf-8"), [Segment(0, 900, "عسلامة")])[1])
    client = TestClient(create_app(runtime, start_worker=False))
    created = client.post("/api/videos", json={"url": "https://youtu.be/dQw4w9WgXcQ", "title": "Demo clip"}).json()["video"]
    runtime.worker.run_once()

    video = client.get(f"/api/videos/{created['id']}").json()
    assert video["stage"] == "processed", video
    assert video["media"]["video_available"] and video["media"]["audio_available"]
    video_file, audio_file = Path(video["media"]["video_path"]), Path(video["media"]["audio_path"])
    assert video_file.parent == runtime.settings.media_root / "Videos" / "YouTube"
    assert audio_file.parent == runtime.settings.media_root / "Audio" / "YouTube"
    assert video_file.stem == audio_file.stem and video_file.suffix == ".mp4" and audio_file.suffix == ".wav"

    streamed = client.get(f"/api/videos/{created['id']}/media/video")
    assert streamed.status_code == 200 and streamed.headers["content-type"] == "video/mp4"
    info = client.get("/api/media").json()
    assert info["video_count"] == 1 and info["audio_count"] == 1

    # Complete removes working copies but keeps the organized files.
    runtime.repository.transition(created["id"], "done")
    runtime.repository.complete(created["id"])
    assert video_file.is_file() and audio_file.is_file()
    # Delete removes them.
    assert client.delete(f"/api/videos/{created['id']}").status_code == 204
    assert not video_file.exists() and not audio_file.exists()


def test_open_endpoints_use_the_system_opener(runtime, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(media, "open_path", lambda path, reveal=False: opened.append((path, reveal)))
    client = TestClient(create_app(runtime, start_worker=False))
    assert client.post("/api/media/open", json={"folder": "videos"}).status_code == 204
    assert opened == [(runtime.settings.media_root / "Videos", False)]
    assert (runtime.settings.media_root / "Videos").is_dir()
    assert client.post("/api/media/open", json={"folder": "../etc"}).status_code == 422
    assert client.post("/api/videos/missing/media/open", json={"kind": "video"}).status_code == 404


def test_tiktok_video_mode_prefers_muxed_mp4() -> None:
    from backend.app.tiktok_audio import video_urls

    urls = video_urls({
        "bitrateAudioInfo": [{"Bitrate": 1, "UrlList": {"MainUrl": "https://audio"}}],
        "bitrateInfo": [{"Format": "mp4", "Bitrate": 5, "PlayAddr": {"UrlList": ["https://video-hd"]}},
                        {"Format": "mp4", "Bitrate": 9, "PlayAddr": {"UrlList": ["https://video-best"]}}],
        "playAddr": "https://play",
    })
    assert urls[:3] == ["https://video-best", "https://video-hd", "https://play"]
    assert urls[-1] == "https://audio"


@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is required for the end-to-end media test")
def test_reprocess_upgrades_legacy_audio_only_downloads(runtime, monkeypatch) -> None:
    import json

    calls = []

    def fake_download(*, ytdlp, ffmpeg, source_url, output):
        calls.append(source_url)
        return [FFMPEG, "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=1",
                "-f", "lavfi", "-i", "sine=duration=1", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(output).replace("%(ext)s", "mp4")]

    monkeypatch.setattr(media, "video_download_command", fake_download)
    monkeypatch.setattr(type(runtime.runner), "_transcribe_farukstt",
                        lambda self, audio_path, raw_path: (raw_path.write_text("{}", encoding="utf-8"), [Segment(0, 900, "نص")])[1])
    client = TestClient(create_app(runtime, start_worker=False))
    video_id = client.post("/api/videos", json={"url": "https://www.youtube.com/shorts/dQw4w9WgXcQ"}).json()["video"]["id"]
    runtime.worker.run_once()
    with runtime.repository.connection() as connection:
        connection.execute("UPDATE checkpoints SET metadata_json = ? WHERE video_id = ? AND step = 'download'",
                           (json.dumps({"kind": "yta_audio"}), video_id))
        connection.commit()
    runtime.repository.create_run(video_id, action="reprocess", model_key="farukstt", model_label="FarukSTT",
                                  model_source="medyas/FarukSTT", owner_asserted=True)
    runtime.worker.run_once()
    assert len(calls) == 2
    assert runtime.repository.hydrate_video(video_id)["stage"] == "processed"
