"""Local accounts, revocable sessions and server-side OAuth authorization-code flows."""
import base64
import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from . import store

router = APIRouter(prefix='/api/auth')
current_user = contextvars.ContextVar('current_user', default=None)
SESSION_COOKIE = 'dauys_session'
CSRF_COOKIE = 'dauys_csrf'
OAUTH_COOKIE = 'dauys_oauth'
SESSION_TTL = 12 * 3600
IDLE_TTL = 2 * 3600
PUBLIC = {'/api/auth/session', '/api/auth/login', '/api/auth/register'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def origin():
    value = os.getenv('DAUYS_PUBLIC_URL', 'http://127.0.0.1:8765').rstrip('/')
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise RuntimeError('DAUYS_PUBLIC_URL must be an origin without credentials or path')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1')):
        raise RuntimeError('DAUYS_PUBLIC_URL requires HTTPS outside localhost')
    return value


def cookie(response, name, value, age):
    response.set_cookie(name, value, httponly=True, secure=origin().startswith('https:'),
                        samesite='lax', max_age=age, path='/')


def init():
    with store.connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, login TEXT UNIQUE, name TEXT NOT NULL, email TEXT,
          password_hash TEXT, provider TEXT NOT NULL, subject TEXT,
          created REAL NOT NULL, UNIQUE(provider,subject));
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL,
          expires REAL NOT NULL, seen REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS auth_attempts (bucket TEXT NOT NULL, at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS auth_attempt_bucket ON auth_attempts(bucket,at);
        CREATE TABLE IF NOT EXISTS oauth_states (
          state_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, provider TEXT NOT NULL,
          verifier TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS auth_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        con.execute("DELETE FROM auth_meta WHERE key='setup_hash'")


def claim_legacy(con, user_id):
    """Called inside the transaction that creates the first account only."""
    for row in con.execute('SELECT id,payload FROM meetings').fetchall():
        item = json.loads(row['payload'])
        if not item.get('owner_id'):
            item['owner_id'] = user_id
            con.execute('UPDATE meetings SET payload=? WHERE id=?', (json.dumps(item,ensure_ascii=False),row['id']))


def password_hash(password):
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256*1024*1024)
    return 'scrypt$' + salt.hex() + '$' + value.hex()


def password_matches(password, encoded):
    try:
        _, salt, expected = encoded.split('$')
        value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**17, r=8, p=1, maxmem=256*1024*1024)
        return hmac.compare_digest(value.hex(), expected)
    except (ValueError, AttributeError):
        return False


def public_user(user):
    return {key: user[key] for key in ('id', 'name', 'email', 'provider')}


def session(request):
    token = request.cookies.get(SESSION_COOKIE, '')
    if not token:
        return None
    now = time.time()
    with store.connect() as con:
        row = con.execute('SELECT users.*,sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>? AND seen>?',
                          (digest(token), now, now-IDLE_TTL)).fetchone()
        if row:
            con.execute('UPDATE sessions SET seen=? WHERE token_hash=?', (now, digest(token)))
    return dict(row) if row else None


def new_session(response, user, request):
    token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), time.time()
    with store.connect() as con:
        con.execute('DELETE FROM sessions WHERE expires<? OR seen<? OR token_hash=?',
                    (now, now-IDLE_TTL, digest(request.cookies.get(SESSION_COOKIE, ''))))
        con.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (digest(token), user['id'], csrf, now+SESSION_TTL, now))
    cookie(response, SESSION_COOKIE, token, SESSION_TTL)
    response.delete_cookie(CSRF_COOKIE, path='/')
    return {'user': public_user(user), 'token': csrf}


def csrf_valid(request, user):
    expected = user['csrf'] if user else request.cookies.get(CSRF_COOKIE, '')
    provided = request.headers.get('x-csrf-token', '')
    return bool(expected and provided and hmac.compare_digest(expected.encode(), provided.encode()))


def throttle(request, identity, action):
    # Do not trust X-Forwarded-For from an untrusted caller.
    ip = request.client.host if request.client else 'unknown'
    buckets = [(digest(action + ':ip:' + ip), 30), (digest(action + ':account:' + identity), 10)]
    now = time.time()
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('DELETE FROM auth_attempts WHERE at<?', (now-900,))
        for bucket, maximum in buckets:
            if con.execute('SELECT COUNT(*) FROM auth_attempts WHERE bucket=?', (bucket,)).fetchone()[0] >= maximum:
                raise HTTPException(429, 'Слишком много попыток. Попробуйте через 15 минут.', headers={'Retry-After':'900'})
        con.executemany('INSERT INTO auth_attempts VALUES(?,?)', [(b,now) for b,_ in buckets])


def providers():
    return {p: bool(os.getenv('DAUYS_'+p.upper()+'_CLIENT_ID') and os.getenv('DAUYS_'+p.upper()+'_CLIENT_SECRET')) for p in ('google','facebook')}


@router.get('/session')
def session_info(request: Request, response: Response):
    user = current_user.get()
    csrf = user['csrf'] if user else request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    if not user:
        cookie(response, CSRF_COOKIE, csrf, 3600)
    return {'user': public_user(user) if user else None, 'token': csrf, 'providers': providers()}


class Register(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    password_confirm: str = Field(min_length=12, max_length=128)


def email_login(email):
    email = email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise HTTPException(400, 'Введите корректный email.')
    return email


@router.post('/register', status_code=201)
def register(body: Register, request: Request, response: Response):
    login = email_login(body.email)
    throttle(request, login, 'register')
    if not hmac.compare_digest(body.password.encode(), body.password_confirm.encode()):
        raise HTTPException(400, 'Пароли не совпадают.')
    if not body.name.strip() or len(body.password.strip()) < 12:
        raise HTTPException(400, 'Укажите имя и пароль минимум из 12 символов.')
    encoded = password_hash(body.password)
    user = {'id': uuid.uuid4().hex, 'name':body.name.strip(), 'email':login, 'provider':'email'}
    try:
        with store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            first_account = con.execute('SELECT 1 FROM users LIMIT 1').fetchone() is None
            con.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)', (user['id'],login,user['name'],login,encoded,'email',None,time.time()))
            if first_account:
                claim_legacy(con, user['id'])
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Регистрация с этими данными недоступна. Попробуйте войти.')
    return new_session(response, user, request)


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


@router.post('/login')
def login(body: Login, request: Request, response: Response):
    email = body.email.strip().lower()
    throttle(request, email, 'login')
    with store.connect() as con:
        row = con.execute('SELECT * FROM users WHERE login=? AND provider=?', (email,'email')).fetchone()
    # Same expensive operation for unknown users to reduce account discovery by timing.
    encoded = row['password_hash'] if row else 'scrypt$'+'00'*16+'$'+'00'*64
    valid = password_matches(body.password, encoded)
    if not row or not valid:
        raise HTTPException(401, 'Неверный email или пароль.')
    return new_session(response, dict(row), request)


@router.post('/logout')
def logout(request: Request, response: Response):
    with store.connect() as con:
        con.execute('DELETE FROM sessions WHERE token_hash=?', (digest(request.cookies.get(SESSION_COOKIE,'')),))
    response.delete_cookie(SESSION_COOKIE, path='/')
    return {'ok': True}


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@router.post('/password')
def change_password(body: PasswordChange, request: Request, response: Response):
    user = current_user.get()
    throttle(request, user['id'], 'password')
    if not password_matches(body.current_password, user['password_hash']):
        raise HTTPException(400, 'Текущий пароль указан неверно.')
    if len(body.new_password.strip()) < 12:
        raise HTTPException(400, 'Пароль должен содержать минимум 12 символов.')
    encoded = password_hash(body.new_password)
    with store.connect() as con:
        con.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded,user['id']))
        con.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
    return new_session(response, user, request)


def provider_config(provider):
    if provider not in providers() or not providers()[provider]:
        raise HTTPException(503, 'Вход через этот сервис ещё не настроен администратором.')
    return os.environ['DAUYS_'+provider.upper()+'_CLIENT_ID'], os.environ['DAUYS_'+provider.upper()+'_CLIENT_SECRET']


@router.post('/oauth/{provider}/start')
def oauth_start(provider: str, request: Request, response: Response):
    client_id, _ = provider_config(provider)
    throttle(request, provider, 'oauth')
    state, browser, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    with store.connect() as con:
        con.execute('DELETE FROM oauth_states WHERE expires<?', (time.time(),))
        con.execute('INSERT INTO oauth_states VALUES(?,?,?,?,?)', (digest(state),digest(browser),provider,verifier,time.time()+600))
    cookie(response, OAUTH_COOKIE, browser, 600)
    params = {'client_id':client_id, 'redirect_uri':origin()+'/api/auth/oauth/'+provider+'/callback', 'response_type':'code', 'state':state}
    if provider == 'google':
        params.update(scope='openid email profile', code_challenge_method='S256', code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode())
        endpoint = 'https://accounts.google.com/o/oauth2/v2/auth'
    else:
        params.update(scope='email,public_profile')
        endpoint = 'https://www.facebook.com/'+os.getenv('DAUYS_FACEBOOK_API_VERSION','v23.0')+'/dialog/oauth'
    return {'url':endpoint+'?'+urlencode(params)}


async def exchange_identity(provider, code, verifier):
    client_id, secret = provider_config(provider)
    form = {'client_id':client_id, 'client_secret':secret, 'code':code,
            'redirect_uri':origin()+'/api/auth/oauth/'+provider+'/callback'}
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        if provider == 'google':
            form.update(grant_type='authorization_code', code_verifier=verifier)
            token_response = await client.post('https://oauth2.googleapis.com/token', data=form)
            token_response.raise_for_status()
            token = token_response.json()['access_token']
            info = await client.get('https://openidconnect.googleapis.com/v1/userinfo', headers={'Authorization':'Bearer '+token})
            info.raise_for_status()
            profile = info.json()
            if not profile.get('sub') or profile.get('email_verified') is not True:
                raise ValueError('Verified Google identity required')
            return str(profile['sub']), profile.get('name') or 'Участник', profile.get('email')
        version = os.getenv('DAUYS_FACEBOOK_API_VERSION','v23.0')
        token_response = await client.post(f'https://graph.facebook.com/{version}/oauth/access_token', data=form)
        token_response.raise_for_status()
        token = token_response.json()['access_token']
        proof = hmac.new(secret.encode(),token.encode(),hashlib.sha256).hexdigest()
        info = await client.get(f'https://graph.facebook.com/{version}/me', params={'fields':'id,name,email','appsecret_proof':proof},headers={'Authorization':'Bearer '+token})
        info.raise_for_status()
        profile = info.json()
        if not profile.get('id'):
            raise ValueError('Facebook identity required')
        return str(profile['id']), profile.get('name') or 'Участник', profile.get('email')


@router.get('/oauth/{provider}/callback')
async def oauth_callback(provider: str, request: Request, state: str = '', code: str = '', error: str = ''):
    response = RedirectResponse('/?auth_error=oauth_failed', status_code=303)
    response.delete_cookie(OAUTH_COOKIE, path='/')
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM oauth_states WHERE state_hash=?', (digest(state),)).fetchone()
        if not row or row['provider'] != provider or row['expires'] < time.time() or not hmac.compare_digest(row['browser_hash'],digest(request.cookies.get(OAUTH_COOKIE,''))):
            return response
        con.execute('DELETE FROM oauth_states WHERE state_hash=?', (digest(state),))
    if error or not code:
        return response
    try:
        subject, name, email = await exchange_identity(provider, code, row['verifier'])
        with store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            user = con.execute('SELECT * FROM users WHERE provider=? AND subject=?', (provider,subject)).fetchone()
            if not user:
                uid = uuid.uuid4().hex
                first_account = con.execute('SELECT 1 FROM users LIMIT 1').fetchone() is None
                # Never link accounts merely because provider emails match.
                con.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)', (uid,None,str(name)[:100],email,None,provider,subject,time.time()))
                if first_account:
                    claim_legacy(con, uid)
                user = con.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        response = RedirectResponse('/', status_code=303)
        new_session(response, dict(user), request)
        response.delete_cookie(OAUTH_COOKIE, path='/')
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # Do not reflect provider messages/tokens into URLs, HTML, or logs.
        pass
    return response
