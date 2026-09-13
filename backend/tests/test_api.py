from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_api_requires_explicit_tunisian_confirmation_and_accepts_model_choice(runtime) -> None:
    client = TestClient(create_app(runtime, start_worker=False))
    saved = client.post("/api/videos", json={"url": "fixture://tunisian-demo", "tags": []})
    assert saved.status_code == 201
    video_id = saved.json()["video"]["id"]

    missing_confirmation = client.post("/api/jobs", json={"video_ids": [video_id], "action": "process", "model_key": "farukstt"})
    assert missing_confirmation.status_code == 422
    assert missing_confirmation.json()["detail"]["code"] == "tunisian_confirmation_required"

    accepted = client.post("/api/jobs", json={"video_ids": [video_id], "action": "process", "model_key": "whisper_large_v3", "owner_asserted_tunisian": True})
    assert accepted.status_code == 202
    assert accepted.json()["accepted"][0]["model_key"] == "whisper_large_v3"
    run_id = accepted.json()["accepted"][0]["id"]
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
