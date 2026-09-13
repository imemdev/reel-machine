from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app import thumbnails


def test_thumbnail_is_saved_reused_and_deleted_with_video(runtime, monkeypatch):
    data = b'\xff\xd8\xff' + b'fixture-image'
    calls = []
    monkeypatch.setattr(thumbnails, 'download_thumbnail', lambda url: calls.append(url) or data)
    client = TestClient(create_app(runtime, start_worker=False))
    video = client.post('/api/videos', json={'url': 'fixture://cover', 'thumbnail_url': 'https://example.com/cover.jpg'}).json()['video']
    assert len(calls) == 1  # Saved on import, before a result card is opened.
    response = client.get(f'/api/videos/{video["id"]}/thumbnail')
    assert response.status_code == 200 and response.content == data
    assert response.headers['content-type'] == 'image/jpeg'
    assert len(calls) == 1
    assert client.delete(f'/api/videos/{video["id"]}').status_code == 204
    assert not (runtime.settings.artifact_root / video['id']).exists()
    assert client.get(f'/api/videos/{video["id"]}/thumbnail').status_code == 404


def test_unavailable_thumbnail_does_not_block_import(runtime, monkeypatch):
    def unavailable(url):
        raise OSError('expired')
    monkeypatch.setattr(thumbnails, 'download_thumbnail', unavailable)
    client = TestClient(create_app(runtime, start_worker=False))
    response = client.post('/api/videos', json={'url': 'fixture://expired-cover', 'thumbnail_url': 'https://example.com/expired'})
    assert response.status_code == 201
    assert client.get(f'/api/videos/{response.json()["video"]["id"]}/thumbnail').status_code == 404


def test_non_image_payload_and_private_urls_rejected():
    import pytest
    with pytest.raises(ValueError):
        thumbnails.image_type(b'<html>not an image</html>')
    with pytest.raises(ValueError):
        thumbnails.validate_url('http://127.0.0.1/private')
