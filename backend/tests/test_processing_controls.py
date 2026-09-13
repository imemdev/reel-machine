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


def queue(client, name, tags=None):
    response = client.post("/api/videos", json={"url": f"fixture://{name}", "tags": tags or ["Test"]})
    assert response.status_code == 201
    video_id = response.json()["video"]["id"]
    return video_id, response.json()["video"]["job"]["id"]


def test_queued_pause_survives_restart_and_resumes_same_model(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    video_id, run_id = queue(client, "paused-queue")
    paused = client.post(f"/api/videos/{video_id}/pause")
    assert paused.status_code == 200 and paused.json()["paused"] is True
    duplicate = client.post("/api/videos", json={"url": "fixture://paused-queue"}).json()
    assert duplicate["duplicate"] and duplicate["video"]["paused"]
    assert duplicate["video"]["job"]["id"] == run_id
    restarted = build_runtime(runtime.settings)
    assert restarted.worker.run_isolated_once() is False
    assert restarted.repository.get_run(run_id)["attempt_count"] == 0
    restarted.worker.resume(video_id)
    assert restarted.worker.run_isolated_once() is True
    result = restarted.repository.hydrate_video(video_id)
    assert result["stage"] == "processed"
    assert [run["id"] for run in restarted.repository.list_runs(video_id)] == [run_id]
    assert result["transcript"]["model_key"] == "farukstt"
    duplicate = client.post("/api/videos", json={"url": "fixture://paused-queue"}).json()
    assert duplicate["video"]["stage"] == "processed"
    assert len(restarted.repository.list_runs(video_id)) == 1


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
        process = runtime.worker.active[video_id][1]
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
    video_id, _ = queue(client, "delete-edited", tags=["Test", "Only this video"])
    other = client.post("/api/videos", json={"url": "fixture://shared-tag", "tags": ["Test"]}).json()["video"]["id"]
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


def test_parallel_capacity_pause_replacement_delete_and_shutdown(runtime, monkeypatch, tmp_path):
    from dataclasses import replace

    runtime = build_runtime(replace(runtime.settings, worker_concurrency=2))
    client = TestClient(create_app(runtime, start_worker=False))
    jobs = [queue(client, f"parallel-{i}") for i in range(3)]
    install_slow_writer(runtime, monkeypatch, tmp_path)
    runtime.worker.start()
    try:
        wait_for(lambda: sum(runtime.repository.get_run(run)["state"] == "running" for _, run in jobs) == 2)
        assert len(runtime.worker.active) == 2
        queued = next((video, run) for video, run in jobs if video not in runtime.worker.active)
        assert runtime.repository.get_run(queued[1])["attempt_count"] == 0
        first, second = list(runtime.worker.active)
        other_process = runtime.worker.active[second][1]
        assert client.post(f"/api/videos/{first}/pause").status_code == 200
        wait_for(lambda: runtime.repository.get_run(queued[1])["state"] == "running")
        assert other_process.poll() is None
        assert len(runtime.worker.active) == 2
        assert client.delete(f"/api/videos/{queued[0]}").status_code == 204
        assert other_process.poll() is None
        processes = [entry[1] for entry in runtime.worker.active.values()]
    finally:
        runtime.worker.stop()
    assert not runtime.worker.active
    assert all(process.poll() is not None for process in processes)
    assert runtime.repository.hydrate_video(first)["paused"]


def test_parallel_fixture_jobs_finish_once(runtime):
    from dataclasses import replace

    runtime = build_runtime(replace(runtime.settings, worker_concurrency=2))
    client = TestClient(create_app(runtime, start_worker=False))
    jobs = [queue(client, f"finish-parallel-{i}") for i in range(5)]
    runtime.worker.start()
    try:
        wait_for(lambda: all(runtime.repository.get_run(run)["state"] == "succeeded" for _, run in jobs), timeout=20)
        assert all(runtime.repository.get_run(run)["attempt_count"] == 1 for _, run in jobs)
    finally:
        runtime.worker.stop()


def test_worker_concurrency_bounds(runtime):
    from dataclasses import replace
    import pytest

    for value in (0, -1, 4, 5):
        with pytest.raises(ValueError, match="WORKER_CONCURRENCY"):
            replace(runtime.settings, worker_concurrency=value)


def test_failed_child_releases_parallel_slot(runtime, monkeypatch):
    from dataclasses import replace

    runtime = build_runtime(replace(runtime.settings, worker_concurrency=2))
    client = TestClient(create_app(runtime, start_worker=False))
    jobs = [queue(client, f"exit-parallel-{i}") for i in range(3)]
    command = runtime.worker._job_command
    monkeypatch.setattr(runtime.worker, "_job_command", lambda run_id:
        [sys.executable, "-c", "raise SystemExit(7)"] if run_id == jobs[0][1] else command(run_id))
    runtime.worker.start()
    try:
        wait_for(lambda: all(runtime.repository.get_run(run)["state"] in {"failed", "succeeded"} for _, run in jobs), timeout=20)
        assert runtime.repository.get_run(jobs[0][1])["error_code"] == "worker_exited"
        assert all(runtime.repository.get_run(run)["state"] == "succeeded" for _, run in jobs[1:])
        config = client.get("/api/config").json()
        assert config["worker_concurrency"] == 2
        assert config["max_batch_size"] == runtime.settings.max_batch_size
    finally:
        runtime.worker.stop()


def test_three_slots_refill_together_in_fifo_order(runtime, monkeypatch, tmp_path):
    from dataclasses import replace

    runtime = build_runtime(replace(runtime.settings, worker_concurrency=3))
    client = TestClient(create_app(runtime, start_worker=False))
    jobs = [queue(client, f"three-slots-{i}") for i in range(6)]
    script = '''
import sys, time
from pathlib import Path
root, run_id = Path(sys.argv[1]), sys.argv[2]
(root / (run_id + '.ready')).touch()
while not (root / (run_id + '.release')).exists():
    time.sleep(0.01)
from backend.app.worker import main
sys.argv = ['worker', '--run-id', run_id]
raise SystemExit(main())
'''
    monkeypatch.setattr(runtime.worker, "_job_command", lambda run_id:
        [sys.executable, "-c", script, str(tmp_path), run_id])
    # Fill slots before the child even claims its DB row: queued != free slot.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        launched = list(pool.map(lambda _: runtime.worker.run_isolated_once(wait=False), range(8)))
    assert sum(launched) == 3
    assert runtime.worker.run_isolated_once(wait=False) is False
    assert list(runtime.worker.active) == [video for video, _ in jobs[:3]]
    try:
        wait_for(lambda: all((tmp_path / (run + ".ready")).exists() for _, run in jobs[:3]))
        processes = [runtime.worker.active[video][1] for video, _ in jobs[:2]]
        for _, run in jobs[:2]:
            (tmp_path / (run + ".release")).touch()
        for process in processes:
            assert process.wait(timeout=10) == 0
        # Both processes have finished before the scheduler's next pass.
        runtime.worker.start()
        wait_for(lambda: all((tmp_path / (run + ".ready")).exists() for _, run in jobs[3:5]))
        assert set(runtime.worker.active) == {video for video, _ in jobs[2:5]}
        assert not (tmp_path / (jobs[5][1] + ".ready")).exists()
        # New arrivals join behind the existing waiting video.
        jobs.append(queue(client, "three-slots-new-arrival"))
        assert len(runtime.worker.active) == 3
        (tmp_path / (jobs[2][1] + ".release")).touch()
        wait_for(lambda: (tmp_path / (jobs[5][1] + ".ready")).exists())
        assert not (tmp_path / (jobs[6][1] + ".ready")).exists()
        for _, run in jobs:
            (tmp_path / (run + ".release")).touch()
        wait_for(lambda: all(runtime.repository.get_run(run)["state"] == "succeeded" for _, run in jobs), timeout=20)
        assert all(runtime.repository.get_run(run)["attempt_count"] == 1 for _, run in jobs)
    finally:
        runtime.worker.stop()


def test_spawn_failure_does_not_stall_queue(runtime, monkeypatch):
    from dataclasses import replace

    runtime = build_runtime(replace(runtime.settings, worker_concurrency=3))
    client = TestClient(create_app(runtime, start_worker=False))
    jobs = [queue(client, f"spawn-failure-{i}") for i in range(4)]
    command = runtime.worker._job_command
    def fail_first(run_id):
        if run_id == jobs[0][1]:
            raise OSError("cannot launch child")
        return command(run_id)
    monkeypatch.setattr(runtime.worker, "_job_command", fail_first)
    runtime.worker.start()
    try:
        wait_for(lambda: all(runtime.repository.get_run(run)["state"] in {"failed", "succeeded"} for _, run in jobs), timeout=20)
        assert runtime.repository.get_run(jobs[0][1])["error_code"] == "worker_start_failed"
        assert all(runtime.repository.get_run(run)["state"] == "succeeded" for _, run in jobs[1:])
    finally:
        runtime.worker.stop()


def test_default_concurrency_is_one(monkeypatch):
    from backend.app.settings import load_settings

    monkeypatch.delenv("WORKER_CONCURRENCY", raising=False)
    assert load_settings().worker_concurrency == 1
    monkeypatch.setenv("WORKER_CONCURRENCY", "3")
    assert load_settings().worker_concurrency == 1


def test_single_worker_failure_moves_to_error_and_continues(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    bad, failed_run = queue(client, 'english-demo')
    good, good_run = queue(client, 'after-failure')
    runtime.worker.start()
    try:
        wait_for(lambda: runtime.repository.get_run(good_run)['state'] == 'succeeded', timeout=20)
        assert runtime.repository.hydrate_video(bad)['stage'] == 'error'
        assert runtime.repository.get_run(failed_run)['state'] == 'failed'
        assert runtime.repository.get_run(failed_run)['attempt_count'] == 1
        assert runtime.repository.hydrate_video(good)['stage'] == 'processed'
        assert runtime.repository.get_run(good_run)['attempt_count'] == 1
    finally:
        runtime.worker.stop()


def test_restart_requeues_old_parallel_jobs_before_single_worker(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    jobs = [queue(client, f"old-parallel-{i}") for i in range(3)]
    for video, run in jobs:
        runtime.repository.claim_run(run)
        runtime.repository.set_run_step(run, "transcribe")
        directory = runtime.artifacts.step_dir(video, run, "transcribe")
        (directory / "partial.json").write_text("partial")
    runtime.worker._recover_interrupted()
    for video, run in jobs:
        assert runtime.repository.get_run(run)["state"] == "queued"
        assert runtime.repository.get_run(run)["current_step"] is None
        assert not (runtime.settings.artifact_root / video / run / "transcribe").exists()
    runtime.worker.start()
    try:
        wait_for(lambda: all(runtime.repository.get_run(run)["state"] == "succeeded" for _, run in jobs), timeout=20)
    finally:
        runtime.worker.stop()


def test_macos_exiting_group_permission_race_is_reaped(runtime, monkeypatch):
    class ExitingProcess:
        pid = 12345
        def poll(self):
            return None
        def wait(self, timeout):
            return 0
    def exiting_group(*args):
        raise PermissionError("exiting process group")
    monkeypatch.setattr("backend.app.runtime.os.killpg", exiting_group)
    runtime.worker.active['test-video'] = ('test-run', ExitingProcess())
    runtime.worker._terminate_active()
    assert runtime.worker.active == {}
