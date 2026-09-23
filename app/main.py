import json
import os
import secrets
import shutil
import uuid
import hashlib
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from . import store, pipeline
from .config import DATA, ROOT, WHISPER, WHISPER_KK, SPEAKER, LLM, LLAMA, MAX_UPLOAD
from .dates import task_state
from .export import pdf_bytes, docx_bytes, anonymize
from . import cache
from . import auth
from .insights import insights, search_segments, followup_agenda, calendar

mutations = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    store.init()
    auth.init()
    (DATA / 'uploads').mkdir(exist_ok=True)
    yield


app = FastAPI(title='Dauys Hunt — от голоса к действиям', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]'])


@app.middleware('http')
async def secure(request, call_next):
    path = request.url.path
    callback = path in ('/api/auth/oauth/google/callback', '/api/auth/oauth/facebook/callback') and request.method == 'GET'
    public = path in auth.PUBLIC or callback or path in ('/api/auth/oauth/google/start', '/api/auth/oauth/facebook/start')
    user = auth.session(request) if path.startswith('/api/') else None
    context_token = auth.current_user.set(user)
    response = None
    try:
        if request.headers.get('sec-fetch-site') == 'cross-site' and not callback:
            response = JSONResponse({'detail':'Доступ с другого сайта запрещён.'}, status_code=403)
        elif path.startswith('/api/') and not public and not user:
            response = JSONResponse({'detail':'Войдите в аккаунт.'}, status_code=401)
        elif request.method not in ('GET','HEAD','OPTIONS'):
            expected_origin = str(request.base_url).rstrip('/')
            supplied_origin = request.headers.get('origin')
            if supplied_origin and supplied_origin != expected_origin:
                response = JSONResponse({'detail':'Недопустимый источник запроса.'}, status_code=403)
            elif not auth.csrf_valid(request, user):
                response = JSONResponse({'detail':'Обновите страницу: токен сессии недействителен.'}, status_code=403)
            else:
                try:
                    length = int(request.headers.get('content-length','0'))
                except ValueError:
                    length = MAX_UPLOAD + 1024*1024 + 1
                limit = 16*1024 if path.startswith('/api/auth/') else MAX_UPLOAD + 1024*1024
                if length > limit:
                    response = JSONResponse({'detail':'Размер запроса превышает допустимый.'}, status_code=413)
                elif path.startswith('/api/auth/') and request.headers.get('transfer-encoding'):
                    response = JSONResponse({'detail':'Для запросов входа требуется Content-Length.'}, status_code=411)
                else:
                    async with mutations:
                        response = await call_next(request)
        if response is None:
            response = await call_next(request)
    finally:
        auth.current_user.reset(context_token)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Permissions-Policy'] = 'camera=(), geolocation=(), microphone=(self)'
    if request.url.scheme == 'https':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    response.headers['Cache-Control'] = 'no-store'
    return response


def models_status():
    return {'speech': all((WHISPER / name).is_file() for name in ['model.bin', 'config.json', 'tokenizer.json']),
            'speech_kk': all((WHISPER_KK / name).is_file() for name in ['model.bin', 'config.json', 'tokenizer.json']),
            'speakers': SPEAKER.is_file(), 'analysis': LLM.is_file() and LLAMA.is_file()}


def require_models(speech=True):
    state = models_status()
    if not state['analysis'] or (speech and not (state['speech'] and state['speech_kk'] and state['speakers'])):
        raise HTTPException(503, 'Модели не установлены. Выполните scripts/setup_models.py и обновите страницу.')


def require(mid, editable=False):
    item = store.get(mid)
    user = auth.current_user.get()
    if not item or not user or item.get('owner_id') != user['id']:
        raise HTTPException(404, 'Совещание не найдено.')
    if editable and item['status'] in ('processing', 'queued'):
        raise HTTPException(409, 'Дождитесь завершения обработки.')
    return item


def new_item(title, meeting_date, language, source):
    return {'id': uuid.uuid4().hex, 'title': title, 'date': meeting_date, 'language': language,
        'owner_id': auth.current_user.get()['id'],
        'created_at': datetime.now().isoformat(), 'status': 'queued', 'stage': 'В очереди', 'progress': 0,
        'source': source, 'segments': [], 'speakers': {}, 'summary': '', 'decisions': [], 'tasks': [], 'warnings': [], 'error': None,
        'processing_mode': 'accurate', 'timings': {}, 'cache_hit': False}


@app.get('/api/bootstrap')
def bootstrap():
    return {'token': auth.current_user.get()['csrf'], 'models': models_status(), 'offline': True, 'max_upload_mb': MAX_UPLOAD // 1024 // 1024,
            'version': '0.3.1', 'active_jobs': len(pipeline.active)}


@app.get('/api/meetings')
def list_meetings():
    result = []
    for item in store.all_meetings(auth.current_user.get()['id']):
        result.append({**{k: item.get(k) for k in ['id', 'title', 'date', 'status', 'stage', 'progress', 'duration', 'source', 'error', 'timings', 'cache_hit', 'processing_mode']},
                       'needs_review': item.get('speech_quality', {}).get('needs_review', False),
                       'task_count': len(item['tasks']), 'speaker_count': len(item['speakers']),
                       'done_count': sum(t['status'] == 'done' for t in item['tasks'])})
    return result


@app.post('/api/meetings', status_code=202)
async def upload(file: UploadFile = File(...), title: str = Form(..., min_length=1, max_length=200),
                 meeting_date: date = Form(...), language: Literal['auto', 'ru', 'kk', 'mixed'] = Form('auto'),
                 speaker_count: int = Form(0, ge=0, le=20), consent: bool = Form(False),
                 processing_mode: Literal['fast', 'accurate'] = Form('accurate')):
    if not consent:
        raise HTTPException(400, 'Подтвердите, что участники уведомлены о записи и обработке.')
    require_models()
    if len(pipeline.active) >= 8:
        raise HTTPException(429, 'В очереди уже 8 записей. Дождитесь завершения обработки.')
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in {'.mp3', '.wav', '.m4a', '.ogg', '.webm', '.mp4', '.flac', '.aac', '.mkv'}:
        raise HTTPException(400, 'Поддерживаются MP3, WAV, M4A, OGG, WEBM, MP4, FLAC, AAC, MKV.')
    item = new_item(title.strip() or 'Совещание', meeting_date.isoformat(), language, 'audio')
    item.update(filename=Path(file.filename).name, audio_file=f"uploads/{item['id']}{suffix}", speaker_count=speaker_count, consent=True, processing_mode=processing_mode)
    target = DATA / item['audio_file']
    size = 0
    digest = hashlib.sha256()
    try:
        with target.open('wb') as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, 'Размер записи превышает 250 МБ.')
                output.write(chunk)
                digest.update(chunk)
        if size == 0:
            raise HTTPException(400, 'Файл пустой.')
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    item['cache_key'] = cache.key_for(digest.hexdigest(), item)
    store.save(item, 'Загружена запись; уведомление участников подтверждено')
    pipeline.submit(item['id'])
    return {'id': item['id']}


class TranscriptInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    date: date
    text: str = Field(min_length=10, max_length=100000)
    consent: bool = False


@app.post('/api/transcripts', status_code=202)
def import_transcript(body: TranscriptInput):
    if not body.consent:
        raise HTTPException(400, 'Требуется подтверждение уведомления участников.')
    require_models(False)
    item = new_item(body.title, body.date.isoformat(), 'mixed', 'text')
    names = {}
    for line in body.text.splitlines():
        if not line.strip():
            continue
        name, sep, text = line.partition(':')
        if not sep or len(name) > 100:
            name, text = 'Участник', line
        name = name.strip()
        if name not in names:
            names[name] = f'S{len(names) + 1}'
        item['segments'].append({'id': len(item['segments']) + 1, 'speaker': names[name], 'text': text.strip(), 'start': 0, 'end': 0, 'confidence': None})
    if not item['segments']:
        raise HTTPException(400, 'Текст не содержит реплик.')
    item['speakers'] = {value: key for key, value in names.items()}
    item['warnings'] = ['Импортирован текст. Распознавание аудио и акустическая диаризация для этого совещания не выполнялись.']
    store.save(item, 'Импортирован текст')
    pipeline.submit(item['id'], speech=False)
    return {'id': item['id']}


@app.get('/api/meetings/{mid}')
def get_meeting(mid: str):
    item = require(mid)
    for t in item['tasks']:
        t['computed_status'] = task_state(t)
    item['insights'] = insights(item)
    return item


@app.get('/api/meetings/{mid}/search')
def search_meeting(mid: str, q: str = ''):
    if len(q) > 300:
        raise HTTPException(400, 'Поисковый запрос слишком длинный.')
    return search_segments(require(mid), q)


@app.get('/api/meetings/{mid}/agenda')
def agenda(mid: str):
    item = require(mid, True)
    return Response(followup_agenda(item).encode('utf-8'), media_type='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="followup-agenda.md"'})


@app.get('/api/meetings/{mid}/calendar')
def calendar_export(mid: str):
    item = require(mid, True)
    return Response(calendar(item), media_type='text/calendar; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="dauys-tasks.ics"'})


@app.get('/api/meetings/{mid}/audio')
def audio(mid: str):
    item = require(mid)
    if not item.get('audio_file'):
        raise HTTPException(404, 'У этого совещания нет аудиозаписи.')
    return FileResponse(DATA / item['audio_file'])


@app.post('/api/meetings/{mid}/retry', status_code=202)
def retry(mid: str):
    item = require(mid, True)
    if item['status'] != 'error':
        raise HTTPException(409, 'Повторная обработка доступна после ошибки.')
    require_models(item['source'] == 'audio' and not item['segments'])
    item.update(status='queued', stage='В очереди', error=None)
    store.save(item)
    pipeline.submit(mid, speech=item['source'] == 'audio' and not item['segments'])
    return {'id': mid}


class Retranscribe(BaseModel):
    language: Literal['auto', 'ru', 'kk', 'mixed']


@app.post('/api/meetings/{mid}/retranscribe', status_code=202)
def retranscribe(mid: str, body: Retranscribe):
    original = require(mid, True)
    if not original.get('audio_file'):
        raise HTTPException(400, 'Для повторного распознавания нужна аудиозапись.')
    require_models()
    if len(pipeline.active) >= 8:
        raise HTTPException(429, 'В очереди уже 8 записей.')
    item = new_item((original['title'][:175] + ' · новое распознавание'), original['date'], body.language, 'audio')
    source = DATA / original['audio_file']
    item.update(audio_file=f"uploads/{item['id']}{source.suffix}", filename=original.get('filename'),
                speaker_count=original.get('speaker_count', 0), consent=original.get('consent', True))
    shutil.copyfile(source, DATA / item['audio_file'])
    # Deliberately no cache: preserve the previous transcript and force fresh ASR.
    store.save(item, 'Повторное распознавание: исходный протокол сохранён')
    pipeline.submit(item['id'])
    return {'id': item['id']}


class TaskEdit(BaseModel):
    title: str = Field(min_length=1, max_length=2000)
    assignee: str = Field(max_length=200)
    speaker_id: str = ''
    due_date: date | None = None
    status: Literal['todo', 'in_progress', 'done']
    priority: Literal['normal', 'high']
    reviewed: bool


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=2000)
    assignee: str = Field(default='', max_length=200)
    due_date: date | None = None
    evidence_ids: list[int] = Field(min_length=1, max_length=30)


@app.post('/api/meetings/{mid}/tasks', status_code=201)
def add_task(mid: str, body: TaskCreate):
    item = require(mid, True)
    segments = {s['id']: s for s in item['segments']}
    if any(sid not in segments for sid in body.evidence_ids):
        raise HTTPException(400, 'Укажите существующие реплики-основания.')
    task = {'id': uuid.uuid4().hex, 'title': body.title, 'assignee': body.assignee,
            'due_date': body.due_date.isoformat() if body.due_date else None,
            'evidence_ids': list(dict.fromkeys(body.evidence_ids)),
            'evidence': ' '.join(segments[sid]['text'] for sid in dict.fromkeys(body.evidence_ids)),
            'speaker_id': '', 'deadline_text': '', 'date_uncertain': not bool(body.due_date),
            'status': 'todo', 'priority': 'normal', 'reviewed': False, 'category': 'Добавлено вручную'}
    item['tasks'].append(task)
    store.save(item, 'Добавлено поручение по транскрипту')
    return task


@app.patch('/api/meetings/{mid}/tasks/{tid}')
def edit_task(mid: str, tid: str, body: TaskEdit):
    item = require(mid, True)
    task = next((t for t in item['tasks'] if t['id'] == tid), None)
    if task is None:
        raise HTTPException(404, 'Поручение не найдено.')
    if body.speaker_id and body.speaker_id not in item['speakers']:
        raise HTTPException(400, 'Неизвестный участник.')
    task.update(body.model_dump(mode='json'))
    if body.reviewed:
        task['date_uncertain'] = not bool(body.due_date)
    store.save(item, 'Поручение отредактировано')
    return task


class SpeakerEdit(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@app.patch('/api/meetings/{mid}/speakers/{sid}')
def edit_speaker(mid: str, sid: str, body: SpeakerEdit):
    item = require(mid, True)
    if sid not in item['speakers']:
        raise HTTPException(404, 'Участник не найден.')
    item['speakers'][sid] = body.name
    for t in item['tasks']:
        if t.get('speaker_id') == sid:
            t['assignee'] = body.name
    store.save(item, 'Подтверждено имя участника')
    return {'ok': True}


class SegmentEdit(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    speaker: str


@app.patch('/api/meetings/{mid}/segments/{sid}')
def edit_segment(mid: str, sid: int, body: SegmentEdit):
    item = require(mid, True)
    segment = next((s for s in item['segments'] if s['id'] == sid), None)
    if not segment or body.speaker not in item['speakers']:
        raise HTTPException(400, 'Реплика или участник не найдены.')
    segment.update(body.model_dump())
    for t in item['tasks']:
        if sid in t['evidence_ids']:
            t['evidence'] = ' '.join(s['text'] for s in item['segments'] if s['id'] in t['evidence_ids'])
            t['reviewed'] = False
    store.save(item, 'Исправлен транскрипт')
    return {'ok': True}


@app.delete('/api/meetings/{mid}')
def delete_meeting(mid: str):
    item = require(mid, True)
    if item.get('audio_file'):
        (DATA / item['audio_file']).unlink(missing_ok=True)
    (DATA / f'{mid}.log').unlink(missing_ok=True)
    store.delete(mid)
    return {'ok': True}


@app.get('/api/meetings/{mid}/export/{kind}')
def export(mid: str, kind: Literal['pdf', 'docx', 'json'], anonymous: bool = False):
    item = require(mid, True)
    if item['status'] != 'ready':
        raise HTTPException(409, 'Экспорт доступен после формирования протокола.')
    if anonymous:
        item = anonymize(item)
    if kind == 'json':
        item.pop('audio_file', None)
        item.pop('filename', None)
        content, media = json.dumps(item, ensure_ascii=False, indent=2).encode(), 'application/json'
    elif kind == 'pdf':
        content, media = pdf_bytes(item), 'application/pdf'
    else:
        content, media = docx_bytes(item), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="protocol-{mid[:8]}.{kind}"'})


@app.get('/api/notifications')
def notifications():
    today = date.today()
    result = []
    for item in store.all_meetings(auth.current_user.get()['id']):
        for task in item['tasks']:
            if task['status'] == 'done' or not task.get('due_date'):
                continue
            due = date.fromisoformat(task['due_date'])
            if due <= today + timedelta(days=2):
                result.append({'id': task['id'], 'meeting_id': item['id'], 'meeting_title': item['title'],
                    'title': task['title'], 'assignee': task['assignee'], 'due_date': task['due_date'],
                    'kind': 'overdue' if due < today else 'due', 'uncertain': task.get('date_uncertain', False)})
    return sorted(result, key=lambda t: t['due_date'])


app.include_router(auth.router)
app.mount('/', StaticFiles(directory=ROOT / 'web', html=True), name='web')
