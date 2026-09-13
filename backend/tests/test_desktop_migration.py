from pathlib import Path
import importlib.util
import sqlite3
from fastapi.testclient import TestClient
from backend.app.main import create_app

spec = importlib.util.spec_from_file_location('desktop_server', Path(__file__).resolve().parents[2] / 'desktop/server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_migration_preserves_transcript_and_rewrites_paths(runtime, tmp_path):
    client = TestClient(create_app(runtime, start_worker=False))
    video = client.post('/api/videos', json={'url': 'fixture://desktop-migration'}).json()['video']
    client.post('/api/jobs', json={'video_ids': [video['id']], 'action': 'process'})
    runtime.worker.run_once()
    destination = tmp_path / 'Application Support' / 'Kite' / 'library'
    module.migrate(runtime.settings.database_path.parent, destination)
    assert runtime.settings.database_path.exists()
    with sqlite3.connect(destination / 'library.db') as db:
        assert db.execute('SELECT count(*) FROM transcripts').fetchone()[0] == 1
        path = db.execute('SELECT source_audio_path FROM videos').fetchone()[0]
        assert path.startswith(str(destination)) and Path(path).exists()
    (destination / 'keep').write_text('do not overwrite')
    module.migrate(runtime.settings.database_path.parent, destination)
    assert (destination / 'keep').read_text() == 'do not overwrite'
