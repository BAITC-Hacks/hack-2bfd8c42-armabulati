import json
import zipfile
from app import cache, store
from scripts.package_release import build
from test_core import sample


def test_cache_separates_dates_modes_and_speaker_counts():
    item = {'date':'2026-09-23','language':'ru','speaker_count':3,'processing_mode':'accurate'}
    base = cache.key_for('same audio', item)
    for key, value in [('date','2026-09-24'),('language','kk'),('speaker_count',4),('processing_mode','fast')]:
        assert base != cache.key_for('same audio', {**item,key:value})
    assert base != cache.key_for('other audio', item)


def test_cache_snapshot_is_immutable_and_deleted_with_source(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.init()
    item = sample()
    item.update(cache_key='abc',status='ready')
    cache.save(item)
    item['tasks'][0].update(title='Changed after analysis',status='done',reviewed=True)
    restored = {'cache_key':'abc'}
    assert cache.restore(restored)
    assert restored['tasks'][0]['title'] == 'Подготовить отчёт'
    assert restored['tasks'][0]['id'] != item['tasks'][0]['id']
    assert restored['tasks'][0]['status'] == 'todo'
    assert not restored['tasks'][0]['reviewed']
    store.delete(item['id'])
    assert not cache.restore({'cache_key':'abc'})


def test_release_excludes_private_and_runtime_files(tmp_path):
    archive = build(tmp_path)
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        assert 'dauys-hunt/app/main.py' in names
        assert 'dauys-hunt/web/tools.js' in names
        assert 'dauys-hunt/README.md' in names
        for name in names:
            assert not any(part in name.split('/') for part in ('data','models','runtime','.venv','.git','__pycache__'))
            assert not name.endswith(('.mp3','.gguf','.sqlite3','.log','.env'))
