from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
import pytest
from backend.app.main import create_app
from backend.app.estimates import queue_estimates


def add(runtime, name, duration=60000):
    client = TestClient(create_app(runtime, start_worker=False))
    video = client.post('/api/videos', json={'url': f'fixture://{name}', 'duration_ms': duration}).json()['video']
    return video['id'], video['job']['id']


def sample(runtime, name, duration, seconds, state='succeeded', platform='instagram'):
    video, run = add(runtime, name, duration)
    runtime.repository.record_transcription_time(run, seconds, duration)
    with runtime.repository.connection() as db:
        db.execute('UPDATE runs SET state=? WHERE id=?', (state, run))
        db.execute("UPDATE videos SET stage='processed', active_run_id=NULL, platform=? WHERE id=?", (platform, video))
        db.commit()


def estimates(runtime, clock=None):
    with runtime.repository.connection() as db:
        return queue_estimates(db, clock)


def test_cold_start_and_unknown_duration(runtime):
    video, _ = add(runtime, 'cold-start', None)
    assert estimates(runtime)[video]['status'] == 'learning'
    assert estimates(runtime)[video]['estimated_finish_at'] is None
    sample(runtime, 'history', 60000, 60)
    assert estimates(runtime)[video]['status'] == 'unknown_duration'


def test_weighted_speed_live_countdown_and_overdue(runtime):
    sample(runtime, 'one-minute', 60000, 60)
    sample(runtime, 'two-minutes', 120000, 120)
    video, run = add(runtime, 'current', 120000)
    runtime.repository.claim_run(run)
    runtime.repository.set_run_step(run, 'transcribe')
    clock = datetime.now(timezone.utc)
    with runtime.repository.connection() as db:
        db.execute('UPDATE step_clocks SET started_at=? WHERE run_id=?', ((clock-timedelta(seconds=30)).isoformat(), run))
        db.commit()
    value = estimates(runtime, clock)[video]
    assert value['transcription_seconds'] == 120
    assert value['remaining_seconds'] == 90
    assert value['sample_count'] == 2
    assert estimates(runtime, clock+timedelta(seconds=40))[video]['remaining_seconds'] == 50
    late = estimates(runtime, clock+timedelta(seconds=91))[video]
    assert late['status'] == 'overdue'
    assert late['remaining_seconds'] is None and late['estimated_finish_at'] is None


def test_bad_samples_excluded_and_recent_history_updates(runtime):
    sample(runtime, 'good', 60000, 60)
    sample(runtime, 'failure', 60000, 6000, state='failed')
    sample(runtime, 'fixture', 60000, 0.01, platform='fixture')
    video, _ = add(runtime, 'waiting')
    assert estimates(runtime)[video]['transcription_seconds'] == 60
    assert estimates(runtime)[video]['sample_count'] == 1
    sample(runtime, 'slower', 60000, 120)
    assert estimates(runtime)[video]['transcription_seconds'] == 90


def test_paused_excluded_queue_and_unknown_preparation(runtime):
    sample(runtime, 'good', 60000, 60)
    paused, _ = add(runtime, 'paused')
    first, run = add(runtime, 'first')
    second, _ = add(runtime, 'second', 120000)
    runtime.worker.pause(paused)
    values = estimates(runtime)
    assert values[paused]['status'] == 'paused'
    assert values[paused]['queue_position'] is None
    assert values[first]['queue_position'] == 1
    assert values[second]['queue_position'] == 2
    assert values[second]['ahead_seconds'] == 60
    runtime.repository.claim_run(run)
    runtime.repository.set_run_step(run, 'download')
    values = estimates(runtime)
    assert values[first]['status'] == 'preparing'
    assert values[second]['ahead_seconds'] is None
    assert values[second]['estimated_finish_at'] is None


def test_model_source_isolated_and_twenty_sample_window(runtime):
    for i in range(22):
        sample(runtime, f'history-{i}', 60000, 60 if i < 2 else 120)
    video, _ = add(runtime, 'waiting')
    assert estimates(runtime)[video]['sample_count'] == 20
    assert estimates(runtime)[video]['transcription_seconds'] == 120
    with runtime.repository.connection() as db:
        db.execute("UPDATE runs SET model_source='different-model' WHERE video_id=?", (video,))
        db.commit()
    assert estimates(runtime)[video]['status'] == 'learning'
