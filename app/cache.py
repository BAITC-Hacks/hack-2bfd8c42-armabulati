"""Immutable analysis snapshots keyed by audio content and processing options."""
import copy
import hashlib
import json
import uuid
from .config import ROOT
from . import store

PIPELINE_VERSION = '3-kazakh-specialized'


def key_for(digest, item):
    lock = ROOT / 'models.lock.json'
    signature = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else 'unlocked'
    options = {key: item.get(key) for key in ('date', 'language', 'speaker_count', 'processing_mode', 'owner_id')}
    return hashlib.sha256(json.dumps([PIPELINE_VERSION, signature, digest, options], sort_keys=True).encode()).hexdigest()


def restore(item):
    if not item.get('cache_key'):
        return False
    with store.connect() as con:
        row = con.execute('SELECT payload FROM analysis_cache WHERE key=?', (item['cache_key'],)).fetchone()
    if row is None:
        return False
    payload = json.loads(row['payload'])
    # Never share task identities or edited completion states between meetings.
    for task in payload['tasks']:
        task.update(id=uuid.uuid4().hex, status='todo', reviewed=False)
    item.update(payload, cache_hit=True, status='ready', stage='Готово · использован локальный результат', progress=100)
    return True


def save(item):
    if not item.get('cache_key'):
        return
    keys = ('segments', 'speakers', 'tasks', 'summary', 'decisions', 'warnings', 'duration', 'detected_language', 'speech_quality')
    payload = {key: copy.deepcopy(item[key]) for key in keys if key in item}
    with store.connect() as con:
        con.execute('INSERT OR REPLACE INTO analysis_cache(key,payload,source_id) VALUES(?,?,?)',
                    (item['cache_key'], json.dumps(payload, ensure_ascii=False), item['id']))
