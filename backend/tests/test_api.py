from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_save_preview_with_long_social_caption_and_retry_is_idempotent(runtime, monkeypatch):
    client = TestClient(create_app(runtime, start_worker=False))
    caption = "حكاية تونسية مع تفاصيل كثيرة — " * 100
    preview = {
        "url": "https://www.tiktok.com/@example/video/6718335390845095173",
        "title": caption,
        "creator": "Example",
        "thumbnail_url": None,
        "duration_ms": 12000,
        "source_page_url": None,
    }
    monkeypatch.setattr("backend.app.main.inspect_video", lambda url, settings: preview)
    metadata = client.post("/api/videos/preview", json={"url": preview["url"]})
    assert metadata.status_code == 200
    saved = client.post("/api/videos", json={**metadata.json(), "tags": ["Testing"]})
    assert saved.status_code == 201, saved.text
    video = saved.json()["video"]
    assert video["stage"] == "processing"
    assert video["title"] == caption
    assert video["job"]["state"] == "queued"
    assert video["job"]["model_key"] == "farukstt"
    repeated = client.post("/api/videos", json={**metadata.json(), "tags": []})
    assert repeated.status_code == 201
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["video"]["id"] == video["id"]
    assert client.get("/api/videos").json()["count"] == 1
    assert repeated.json()["video"]["job"]["id"] == video["job"]["id"]
    assert len(runtime.repository.list_runs(video["id"])) == 1


def test_save_still_rejects_unbounded_caption(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    response = client.post("/api/videos", json={"url": "fixture://long-caption", "title": "x" * 20_001})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "title"]


def test_api_defaults_to_faruk_without_confirmation_and_rejects_whisper(runtime) -> None:
    client = TestClient(create_app(runtime, start_worker=False))
    saved = client.post("/api/videos", json={"url": "fixture://tunisian-demo", "tags": []})
    assert saved.status_code == 201
    video_id = saved.json()["video"]["id"]

    rejected = client.post("/api/jobs", json={"video_ids": [video_id], "action": "process", "model_key": "whisper_large_v3"})
    assert rejected.status_code == 422
    assert [model["key"] for model in client.get("/api/config").json()["models"]] == ["farukstt"]
    accepted = client.post("/api/jobs", json={"video_ids": [video_id], "action": "process"})
    assert accepted.status_code == 202
    assert accepted.json()["accepted"] == []  # Already queued automatically.
    assert len(accepted.json()["rejected"]) == 1
    run_id = saved.json()["video"]["job"]["id"]
    queued = client.get(f"/api/jobs/{run_id}/logs")
    assert queued.status_code == 200
    assert "No log files yet" in queued.text
    runtime.worker.run_once()
    report = client.get(f"/api/jobs/{run_id}/logs")
    assert report.status_code == 200
    assert "pipeline.jsonl" in report.text
    for step in ("inspect", "download", "prepare_audio", "check_language", "transcribe", "format", "publish"):
        assert f"{step}/step.log" in report.text
    assert report.headers["cache-control"] == "no-store"
    assert client.get("/api/jobs/unknown/logs").status_code == 404


def test_concurrent_duplicate_adds_queue_exactly_one_job(runtime):
    from concurrent.futures import ThreadPoolExecutor

    app = create_app(runtime, start_worker=False)
    def add(_):
        response = TestClient(app).post("/api/videos", json={"url": "fixture://concurrent-add"})
        assert response.status_code == 201
        return response.json()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(add, range(12)))
    assert sum(not result["duplicate"] for result in results) == 1
    assert len({result["video"]["job"]["id"] for result in results}) == 1
    assert len(runtime.repository.list_runs(results[0]["video"]["id"])) == 1


def test_save_and_queue_roll_back_together(runtime, monkeypatch):
    import pytest

    def fail(*args, **kwargs):
        raise RuntimeError("queue unavailable")
    monkeypatch.setattr(runtime.repository, "_create_run", fail)
    client = TestClient(create_app(runtime, start_worker=False))
    with pytest.raises(RuntimeError, match="queue unavailable"):
        client.post("/api/videos", json={"url": "fixture://atomic-add", "tags": ["Rollback"]})
    assert runtime.repository.list_videos() == []
    with runtime.repository.connection() as connection:
        for table in ("runs", "activities", "tags"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
