import copy
from fastapi.testclient import TestClient
from app import store, cache, pipeline
from app.main import app
from test_core import sample
from auth_helpers import register


def test_upload_review_tools_and_repeated_recording(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr('app.main.DATA', tmp_path)
    monkeypatch.setattr('app.main.require_models', lambda *args: None)
    monkeypatch.setattr(pipeline, 'submit', lambda *args, **kwargs: True)
    with TestClient(app, base_url='http://localhost') as client:
        register(client)
        data = {'title':'Проверка','meeting_date':'2026-09-23','language':'ru',
                'speaker_count':1,'consent':'true','processing_mode':'fast'}
        response = client.post('/api/meetings', data=data, files={'file':('meeting.wav', b'test audio bytes', 'audio/wav')})
        assert response.status_code == 202
        mid = response.json()['id']
        item = store.get(mid)
        assert item['processing_mode'] == 'fast' and len(item['cache_key']) == 64
        assert client.post(f'/api/meetings/{mid}/tasks', json={'title':'Задача', 'evidence_ids':[1]}).status_code == 409
        fixture = sample()
        for key in ('segments','speakers','tasks','summary','decisions'):
            item[key] = copy.deepcopy(fixture[key])
        item.update(status='ready', duration=3)
        store.save(item)
        cache.save(item)

        detail = client.get(f'/api/meetings/{mid}').json()
        assert detail['insights']['has_audio_timing']
        assert client.get(f'/api/meetings/{mid}/search', params={'q':'отчёт'}).json()[0]['id'] == 1
        added = client.post(f'/api/meetings/{mid}/tasks', json={'title':'Проверить результат','assignee':'Айдана','due_date':'2026-10-01','evidence_ids':[1]})
        assert added.status_code == 201
        tid = added.json()['id']
        assert client.patch(f'/api/meetings/{mid}/tasks/{tid}', json={'title':'Проверить результат','assignee':'Айдана','due_date':'2026-10-01','status':'todo','priority':'normal','reviewed':True}).status_code == 200
        calendar = client.get(f'/api/meetings/{mid}/calendar')
        assert calendar.status_code == 200 and b'DTSTART;VALUE=DATE:20261001' in calendar.content
        assert 'Проверить результат' in client.get(f'/api/meetings/{mid}/agenda').text
        for kind, signature in [('pdf', b'%PDF-'),('docx',b'PK')]:
            exported = client.get(f'/api/meetings/{mid}/export/{kind}')
            assert exported.status_code == 200 and exported.content.startswith(signature)

        duplicate = client.post('/api/meetings', data=data, files={'file':('renamed.wav', b'test audio bytes', 'audio/wav')}).json()['id']
        monkeypatch.setattr(pipeline, 'analyze', lambda *args: (_ for _ in ()).throw(AssertionError('Cache hit must not call AI')))
        pipeline.process(duplicate, True)
        reused = store.get(duplicate)
        assert reused['status'] == 'ready' and reused['cache_hit']
        assert len(reused['tasks']) == 1  # human edits were not cached
        assert reused['tasks'][0]['id'] != fixture['tasks'][0]['id']
        assert client.get(f'/api/meetings/{mid}/search', params={'q':'x'*301}).status_code == 400
        assert client.post('/api/meetings', data=data, files={'file':('empty.wav',b'','audio/wav')}).status_code == 400


def test_speaker_single_person_skips_model(monkeypatch):
    from app.speech import diarize
    segments=[{'id':1,'start':0,'end':1,'text':'Привет','words':[]}]
    result,speakers,warnings=diarize(None,segments,1)
    assert result[0]['speaker']=='S1' and speakers == {'S1':'Участник 1'}
