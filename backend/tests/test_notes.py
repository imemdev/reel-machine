from fastapi.testclient import TestClient

from backend.app.db import Repository
from backend.app.main import create_app


def test_notes_lifecycle_and_persistence(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    assert client.get('/api/notes').json() == {'items': [], 'count': 0}
    draft = {'title': '  My idea  ', 'description': 'وصف الفكرة', 'script': 'First line\nثاني سطر'}
    response = client.post('/api/notes', json=draft)
    assert response.status_code == 201
    note = response.json()
    note_id = note['id']
    assert note['title'] == 'My idea'
    assert note['done'] is False
    assert client.patch(f'/api/notes/{note_id}', json={'done': True}).json()['done'] is True
    edited = client.patch(f'/api/notes/{note_id}', json={'script': 'Edited\nنص جديد'}).json()
    assert edited['title'] == 'My idea'
    assert edited['description'] == draft['description']
    assert edited['done'] is True
    # Reopening SQLite initializes the schema again without losing saved notes.
    reopened = Repository(runtime.settings.database_path)
    assert reopened.list_notes() == [edited]
    assert client.patch(f'/api/notes/{note_id}', json={'done': False}).json()['done'] is False
    assert client.post('/api/notes', json={'title': 'Another note'}).status_code == 201
    assert client.get('/api/notes').json()['count'] == 2
    assert client.delete(f'/api/notes/{note_id}').status_code == 204
    assert len(Repository(runtime.settings.database_path).list_notes()) == 1
    assert client.patch(f'/api/notes/{note_id}', json={'done': True}).status_code == 404
    assert client.delete(f'/api/notes/{note_id}').status_code == 404


def test_notes_validation_preserves_saved_content(runtime):
    client = TestClient(create_app(runtime, start_worker=False))
    for payload in ({'title': ' '}, {'title': 'x' * 241}, {'title': 'Title', 'script': None}):
        assert client.post('/api/notes', json=payload).status_code == 422
    note = client.post('/api/notes', json={'title': 'Title', 'script': 'Keep me'}).json()
    for payload in ({'title': ''}, {'description': None}, {'script': None}, {'done': None}, {'unexpected': 'value'}):
        assert client.patch(f'/api/notes/{note["id"]}', json=payload).status_code == 422
    assert client.get('/api/notes').json()['items'] == [note]
