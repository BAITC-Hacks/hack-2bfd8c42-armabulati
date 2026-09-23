from fastapi.testclient import TestClient
from app import store
from app.main import app


def test_api_guards_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr('app.main.DATA', tmp_path)
    with TestClient(app, base_url='http://localhost') as client:
        assert client.get('/api/meetings').json() == []
        assert client.post('/api/transcripts', json={}).status_code == 403
        token = client.get('/api/bootstrap').json()['token']
        client.headers['X-Alem-Token'] = token
        assert client.post('/api/transcripts', json={'title':'Тест', 'date':'2026-09-23', 'text':'Тестовая реплика', 'consent':False}).status_code == 400
        assert client.get('/api/meetings', headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
        assert client.get('/api/meetings', headers={'Host':'evil.example'}).status_code == 400
        store.save({'id':'sample','title':'Тест','date':'2026-09-23','status':'ready','tasks':[], 'speakers':{},'segments':[]})
        assert client.get('/api/meetings/sample').json()['title'] == 'Тест'
        assert client.delete('/api/meetings/sample').status_code == 200
        assert client.get('/api/meetings/sample').status_code == 404
