from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.runtime import build_runtime


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for worker state")


def queue(client, name):
    response = client.post("/api/videos", json={"url": f"fixture://{name}", "tags": ["Test"]})
    assert response.status_code == 201
    video_id = response.json()["video"]["id"]
    response = client.post("/api/jobs", json={"video_ids": [video_id], "action": "process", "model_key": "farukstt", "owner_asserted_tunisian": True})
    assert response.status_code == 202
    return video_id, response.json()["accepted"][0]["id"]


def test_queued_pause_survives_restart_and_resumes_same_model(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    video_id, run_id = queue(client, "paused-queue")
    paused = client.post(f"/api/videos/{video_id}/pause")
    assert paused.status_code == 200 and paused.json()["paused"] is True
    restarted = build_runtime(runtime.settings)
    assert restarted.worker.run_isolated_once() is False
    assert restarted.repository.get_run(run_id)["attempt_count"] == 0
    restarted.worker.resume(video_id)
    assert restarted.worker.run_isolated_once() is True
    result = restarted.repository.hydrate_video(video_id)
    assert result["stage"] == "processed"
    assert [run["id"] for run in restarted.repository.list_runs(video_id)] == [run_id]
    assert result["transcript"]["model_key"] == "farukstt"


def install_slow_writer(runtime, monkeypatch, tmp_path):
    script = tmp_path / "slow_worker.py"
    marker = tmp_path / "writer-ready"
    script.write_text('''
import json, os, signal, subprocess, sys, time
from pathlib import Path
from backend.app.db import Repository
settings = json.loads(os.environ["KITE_RUN_SETTINGS"])
repo = Repository(Path(settings["database_path"]), Path(settings["artifact_root"]))
run = repo.claim_run(sys.argv[1])
repo.set_run_step(run["id"], "download")
target = Path(settings["artifact_root"]) / run["video_id"] / run["id"] / "download"
child_code = """
import signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
target = Path(sys.argv[1])
while True:
    target.mkdir(parents=True, exist_ok=True)
    (target / 'partial.wav').write_text(str(time.time()))
    Path(sys.argv[2]).write_text('ready')
    time.sleep(0.02)
"""
subprocess.Popen([sys.executable, "-c", child_code, str(target), sys.argv[2]])
signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True: time.sleep(1)
''')
    # -c keeps the project root importable just like the real -m worker.
    monkeypatch.setattr(runtime.worker, "_job_command", lambda run_id: [sys.executable, "-c", script.read_text(), run_id, str(marker)])
    return marker


def test_delete_running_job_kills_descendants_and_removes_only_its_data(runtime, monkeypatch, tmp_path):
    client = TestClient(create_app(runtime, start_worker=False))
    video_id, run_id = queue(client, "delete-running")
    other = client.post("/api/videos", json={"url": "fixture://keep-me"}).json()["video"]["id"]
    keep = runtime.artifacts.run_dir(other, "retained") / "audio.wav"
    keep.write_bytes(b"keep")
    marker = install_slow_writer(runtime, monkeypatch, tmp_path)
    runtime.worker.start()
    try:
        wait_for(marker.exists)
        process = runtime.worker.active[1]
        queued_id, _ = queue(client, "delete-queued")
        assert client.delete(f"/api/videos/{queued_id}").status_code == 204
        assert process.poll() is None  # Deleting a queued item must not stop another video.
        response = client.delete(f"/api/videos/{video_id}")
        assert response.status_code == 204, response.text
        assert process.poll() is not None
        assert client.get(f"/api/videos/{video_id}").status_code == 404
        assert client.get(f"/api/jobs/{run_id}").status_code == 404
        time.sleep(0.2)
        assert not (runtime.settings.artifact_root / video_id).exists()
        assert keep.read_bytes() == b"keep"
        with runtime.repository.connection() as connection:
            for table in ("runs", "checkpoints", "transcripts", "activities", "video_tags"):
                assert connection.execute(f"SELECT count(*) FROM {table} WHERE video_id = ?", (video_id,)).fetchone()[0] == 0
    finally:
        runtime.worker.stop()


def test_pause_stops_writer_discards_partial_download_and_allows_resume(runtime, monkeypatch, tmp_path):
    client = TestClient(create_app(runtime, start_worker=False))
    video_id, run_id = queue(client, "pause-running")
    marker = install_slow_writer(runtime, monkeypatch, tmp_path)
    runtime.worker.start()
    try:
        wait_for(marker.exists)
        response = client.post(f"/api/videos/{video_id}/pause")
        assert response.status_code == 200 and response.json()["paused"]
        time.sleep(0.2)
        assert not (runtime.settings.artifact_root / video_id / run_id / "download").exists()
        assert runtime.repository.get_run(run_id)["state"] == "queued"
    finally:
        runtime.worker.stop()
    restarted = build_runtime(runtime.settings)
    restarted.worker.resume(video_id)
    assert restarted.worker.run_isolated_once()
    assert restarted.repository.hydrate_video(video_id)["stage"] == "processed"


def test_delete_completed_video_removes_transcripts_and_exports(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    video_id, _ = queue(client, "delete-completed")
    runtime.worker.run_once()
    runtime.repository.transition(video_id, "done")
    runtime.repository.complete(video_id)
    assert client.delete(f"/api/videos/{video_id}").status_code == 204
    assert not (runtime.settings.artifact_root / video_id).exists()


def test_resume_reuses_completed_audio_checkpoint(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    video_id, run_id = queue(client, "resume-checkpoints")
    run = runtime.repository.claim_run(run_id)
    video = runtime.repository.hydrate_video(video_id)
    runner = runtime.runner
    runner._execute_step(video, run, "inspect", lambda: runner._inspect(video, run))
    download = runner._execute_step(video, run, "download", lambda: runner._download(video, run))
    runner._execute_step(video, run, "prepare_audio", lambda: runner._prepare_audio(video, run, download))
    checkpoint = runtime.repository.checkpoint(video_id, "prepare_audio")
    assert client.post(f"/api/videos/{video_id}/pause").status_code == 200
    assert Path(checkpoint["artifact_path"]).is_file()
    assert client.post(f"/api/videos/{video_id}/resume").status_code == 200
    runtime.worker.run_isolated_once()
    assert runtime.repository.hydrate_video(video_id)["stage"] == "processed"
    assert runtime.repository.checkpoint(video_id, "prepare_audio") == checkpoint


def test_delete_removes_edited_transcripts_and_only_unshared_tags(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    video_id, _ = queue(client, "delete-edited")
    other = client.post("/api/videos", json={"url": "fixture://shared-tag", "tags": ["Test"]}).json()["video"]["id"]
    client.patch(f"/api/videos/{video_id}", json={"tags": ["Test", "Only this video"]})
    runtime.worker.run_once()
    video = client.get(f"/api/videos/{video_id}").json()
    assert video["stage"] == "processed" and video["transcript"]
    updated = client.patch(f"/api/videos/{video_id}/transcript", json={"expected_revision_id": video["transcript"]["id"], "segments": [{"start_ms": 0, "end_ms": 1000, "text": "عسلامة"}]})
    assert updated.status_code == 200
    assert client.delete(f"/api/videos/{video_id}").status_code == 204
    assert not (runtime.settings.artifact_root / video_id).exists()
    with runtime.repository.connection() as connection:
        for table in ("transcripts", "runs", "checkpoints", "activities", "video_tags"):
            assert connection.execute(f"SELECT count(*) FROM {table} WHERE video_id = ?", (video_id,)).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM tags WHERE name = 'Only this video'").fetchone()[0] == 0
    assert client.get(f"/api/videos/{other}").json()["tags"] == ["Test"]
