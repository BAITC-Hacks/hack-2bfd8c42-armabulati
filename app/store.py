import json
import sqlite3
from datetime import datetime, timezone
from .config import DATA


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / 'alem.sqlite3', timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con


def init():
    with connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS meetings (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, meeting_id TEXT, action TEXT, at TEXT)')
        rows = con.execute('SELECT id,payload FROM meetings').fetchall()
        for row in rows:
            item = json.loads(row['payload'])
            if item['status'] in ('queued', 'processing'):
                item.update(status='error', stage='Обработка прервана перезапуском. Можно повторить.', error='Сервер был перезапущен.')
                con.execute('UPDATE meetings SET payload=? WHERE id=?', (json.dumps(item, ensure_ascii=False), row['id']))


def save(item, action=None):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.execute('INSERT INTO meetings VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated', (item['id'], json.dumps(item, ensure_ascii=False), now))
        if action:
            con.execute('INSERT INTO audit(meeting_id,action,at) VALUES(?,?,?)', (item['id'], action, now))


def get(mid):
    with connect() as con:
        row = con.execute('SELECT payload FROM meetings WHERE id=?', (mid,)).fetchone()
    return json.loads(row['payload']) if row else None


def all_meetings():
    with connect() as con:
        return [json.loads(r['payload']) for r in con.execute('SELECT payload FROM meetings ORDER BY updated DESC')]


def delete(mid):
    with connect() as con:
        con.execute('DELETE FROM meetings WHERE id=?', (mid,))
        con.execute('DELETE FROM audit WHERE meeting_id=?', (mid,))
