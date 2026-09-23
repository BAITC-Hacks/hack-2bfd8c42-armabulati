from fastapi.testclient import TestClient
from app import store, pipeline
from app.main import app
from auth_helpers import register


def test_retranscribe_preserves_original_and_enforces_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr('app.main.DATA', tmp_path)
    monkeypatch.setattr('app.main.require_models', lambda *args: None)
    monkeypatch.setattr(pipeline, 'submit', lambda *args, **kwargs: True)
    with TestClient(app, base_url='http://localhost') as client:
        user=register(client)
        original={'id':'source','owner_id':user['id'],'title':'Аудио','date':'2026-09-23','status':'ready',
                  'audio_file':'uploads/source.mp3','tasks':[{'title':'Human edit'}],'segments':[], 'speakers':{}}
        (tmp_path/'uploads/source.mp3').write_bytes(b'original audio')
        store.save(original)
        assert client.post('/api/meetings/source/retranscribe',json={'language':'tr'}).status_code==422
        response=client.post('/api/meetings/source/retranscribe',json={'language':'mixed'})
        assert response.status_code==202
        new=store.get(response.json()['id'])
        assert new['owner_id']==user['id'] and new['language']=='mixed'
        assert new['tasks']==[] and 'cache_key' not in new
        assert store.get('source')==original
        assert new['audio_file']!=original['audio_file']
        assert (tmp_path/new['audio_file']).read_bytes()==b'original audio'
        register(client,email='another@example.test')
        assert client.post('/api/meetings/source/retranscribe',json={'language':'kk'}).status_code==404


def test_unreliable_speech_does_not_generate_invented_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.init()
    store.save({'id':'bad','status':'queued','segments':[{'text':'partial'}], 'speech_quality':{'needs_review':True}})
    monkeypatch.setattr(pipeline,'analyze',lambda *args: (_ for _ in ()).throw(AssertionError('Unreliable ASR must not reach LLM')))
    pipeline.process('bad',False)
    item=store.get('bad')
    assert item['status']=='ready' and item['tasks']==[] and item['decisions']==[]
    assert 'проверки' in item['summary']
