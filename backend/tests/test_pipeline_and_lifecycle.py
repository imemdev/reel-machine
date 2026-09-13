from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sys
import pytest

from backend.app.pipeline import PipelineError, _run_logged, gallery_dl_command, yta_command
from backend.app.runtime import build_runtime
from backend.app.settings import load_settings
from backend.app.urls import canonicalize_url
from backend.app.tiktok_audio import audio_urls


def add_fixture(runtime, name: str = "tunisian-demo") -> dict:
    identity = canonicalize_url(f"fixture://{name}", allow_fixture=True)
    video, duplicate = runtime.repository.create_video(
        platform=identity.platform,
        canonical_id=identity.canonical_id,
        canonical_url=identity.canonical_url,
        source_url=identity.source_url,
        source_page_url=identity.source_url,
        title="Fixture",
        creator="Test",
        thumbnail_url=None,
        tags=["Testing"],
    )
    assert not duplicate
    return video


def queue_fixture(runtime, video_id: str, model_key: str = "farukstt", action: str = "process") -> dict:
    label = "FarukSTT" if model_key == "farukstt" else "Whisper Large-v3 (Full)"
    source = "medyas/FarukSTT" if model_key == "farukstt" else "ggml-large-v3.bin"
    run = runtime.repository.create_run(
        video_id,
        action=action,
        model_key=model_key,
        model_label=label,
        model_source=source,
        owner_asserted=True,
    )
    result = runtime.worker.run_once()
    assert result and result["id"] == run["id"]
    return runtime.repository.hydrate_video(video_id)


def test_download_command_uses_yta_login_shell_and_preserves_output_override(tmp_path) -> None:
    command = yta_command(
        yta_function="yta",
        source_url="https://www.instagram.com/reel/example/",
        output=tmp_path / "source.%(ext)s",
    )
    assert command[:3] == ["zsh", "-lic", 'yta "$@"']
    assert command[3:] == ["local-video-library", "https://www.instagram.com/reel/example/", "--output", str(tmp_path / "source.%(ext)s")]


def test_tiktok_download_command_uses_local_gallery_dl_path(tmp_path) -> None:
    command = gallery_dl_command(
        gallery_dl="gallery-dl",
        source_url="https://www.tiktok.com/@scout2015/video/6718335390845095173",
        directory=tmp_path,
    )
    assert command[-1] == "https://www.tiktok.com/@scout2015/video/6718335390845095173"
    assert "--config-ignore" in command
    assert "--directory" in command
    assert "--no-part" in command

    metadata_command = gallery_dl_command(
        gallery_dl="gallery-dl",
        source_url="https://www.tiktok.com/@scout2015/video/6718335390845095173",
        directory=tmp_path,
        dump_json=True,
    )
    assert "--dump-json" in metadata_command


def test_fixture_pipeline_publishes_and_complete_retains_transcript(runtime) -> None:
    video = add_fixture(runtime)
    processed = queue_fixture(runtime, video["id"], "farukstt")
    assert processed["stage"] == "processed"
    assert processed["transcript"]["model_key"] == "farukstt"
    media_path = Path(processed["source_media_path"])
    audio_path = Path(processed["source_audio_path"])
    assert media_path.is_file()
    assert audio_path.is_file()

    done = runtime.repository.transition(video["id"], "done")
    complete = runtime.repository.complete(video["id"])
    assert done["stage"] == "done"
    assert complete["stage"] == "complete"
    assert complete["transcript"]["segments"]
    assert complete["source_media_path"] is None
    assert complete["source_audio_path"] is None
    assert not media_path.exists()
    assert not audio_path.exists()


def test_reprocess_records_the_second_explicit_model_choice(runtime) -> None:
    video = add_fixture(runtime)
    queue_fixture(runtime, video["id"], "farukstt")
    reprocessed = queue_fixture(runtime, video["id"], "whisper_large_v3", "reprocess")
    assert reprocessed["stage"] == "processed"
    assert reprocessed["transcript"]["model_key"] == "whisper_large_v3"
    runs = runtime.repository.list_runs(video["id"])
    assert {run["model_key"] for run in runs} == {"farukstt", "whisper_large_v3"}


def test_retry_reuses_completed_checkpoints_after_a_format_failure(tmp_path) -> None:
    settings = replace(load_settings(), database_path=tmp_path / "library.db", artifact_root=tmp_path / "runs", allow_fixture_sources=True)
    runtime = build_runtime(settings, failure_plan={"format": 1})
    video = add_fixture(runtime)
    failed = queue_fixture(runtime, video["id"], "farukstt")
    assert failed["stage"] == "error"
    assert failed["failed_step"] == "format"
    failed_log = runtime.artifacts.run_dir(video["id"], failed["active_run_id"]) / "format" / "step.log"
    assert '"status": "failed"' in failed_log.read_text()
    assert "injected_failure" in failed_log.read_text()
    old_transcribe = runtime.repository.checkpoint(video["id"], "transcribe")["artifact_path"]

    retried = queue_fixture(runtime, video["id"], "farukstt", "retry")
    assert retried["stage"] == "processed"
    assert runtime.repository.checkpoint(video["id"], "transcribe")["artifact_path"] == old_transcribe
    run = next(item for item in runtime.repository.list_runs(video["id"]) if item["action"] == "retry")
    events = [json.loads(line) for line in (runtime.artifacts.run_dir(video["id"], run["id"]) / "pipeline.jsonl").read_text().splitlines()]
    assert any(event["step"] == "transcribe" and event["status"] == "reused" for event in events)
    assert events[-1]["step"] == "publish" and events[-1]["status"] == "succeeded"


def test_command_log_keeps_command_before_output_and_exit_code(tmp_path):
    log = tmp_path / "command.log"
    with pytest.raises(PipelineError, match="exit code 3"):
        _run_logged([sys.executable, "-c", "print('failure detail'); raise SystemExit(3)"], log, timeout=5)
    content = log.read_text()
    assert content.startswith("$ ")
    assert "failure detail\n\nExit code: 3" in content


def test_missing_audio_has_actionable_error(tmp_path, monkeypatch):
    import subprocess
    def fail(command, **kwargs):
        kwargs["stdout"].write("Stream map '' matches no streams.\nFailed to set value '0:a:0'\n")
        return subprocess.CompletedProcess(command, 234)
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(PipelineError) as caught:
        _run_logged(["/opt/homebrew/bin/ffmpeg"], tmp_path / "ffmpeg.log", timeout=5)
    assert caught.value.code == "audio_stream_missing"
    assert not caught.value.retryable
    assert "Retrying this same file will not help" in caught.value.message


def test_tiktok_selector_prefers_video_audio_not_dash_video_or_music():
    assert audio_urls({
        "bitrateAudioInfo": [
            {"Bitrate": 32, "UrlList": {"MainUrl": "https://cdn/low"}},
            {"Bitrate": 64, "UrlList": {"MainUrl": "https://cdn/high", "BackupUrl": "https://cdn/backup"}},
        ],
        "bitrateInfo": [
            {"Format": "dash", "PlayAddr": {"UrlList": ["https://cdn/video-only"]}},
            {"Format": "mp4", "PlayAddr": {"UrlList": ["https://cdn/muxed"]}},
        ],
        "playAddr": "https://cdn/muxed",
        "music": {"playUrl": "https://cdn/unrelated-song"},
    }) == ["https://cdn/high", "https://cdn/backup", "https://cdn/low", "https://cdn/muxed"]
    assert audio_urls({}) == []
    assert audio_urls({"playAddr": "file:///etc/passwd"}) == []


def test_missing_audio_retry_invalidates_download_but_keeps_old_artifact(runtime):
    video = add_fixture(runtime)
    queue_fixture(runtime, video["id"])
    # Reprocess creates an active run, then simulate the observed missing-audio failure.
    run = runtime.repository.create_run(video["id"], action="reprocess", model_key="farukstt",
                                        model_label="FarukSTT", model_source="medyas/FarukSTT", owner_asserted=True)
    original = runtime.repository.checkpoint(video["id"], "download")
    runtime.repository.mark_error(run_id=run["id"], step="prepare_audio", code="audio_stream_missing",
                                  message="No audio", retryable=False)
    runtime.repository.create_run(video["id"], action="retry", model_key="farukstt",
                                  model_label="FarukSTT", model_source="medyas/FarukSTT", owner_asserted=True)
    assert runtime.repository.checkpoint(video["id"], "download") is None
    assert runtime.repository.checkpoint(video["id"], "prepare_audio") is None
    assert runtime.repository.checkpoint(video["id"], "inspect") is not None
    assert Path(original["artifact_path"]).is_file()
