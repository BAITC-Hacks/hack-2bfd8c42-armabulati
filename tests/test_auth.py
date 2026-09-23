import json
import time
import asyncio
import httpx
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from app import auth, store, cache
from app.main import app
from auth_helpers import register
from test_core import sample


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setattr('app.main.DATA',tmp_path)
    with TestClient(app,base_url='http://localhost') as client:
        yield client


def test_authentication_logout_and_cookie_flags(client):
    assert client.get('/api/bootstrap').status_code == 401
    assert client.get('/api/notifications').status_code == 401
    assert client.post('/api/auth/register',json={'name':'Test','email':'x@y.test','password':'safe long pass'}).status_code == 403
    user=register(client)
    session_cookie=client.cookies.get(auth.SESSION_COOKIE)
    with store.connect() as con:
        row=con.execute('SELECT * FROM users').fetchone()
        session=con.execute('SELECT * FROM sessions').fetchone()
    assert row['password_hash'].startswith('scrypt$') and 'Testing' not in row['password_hash']
    assert session['token_hash'] != session_cookie and session['token_hash']==auth.digest(session_cookie)
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/meetings').status_code == 401
    client.headers['X-CSRF-Token']=client.get('/api/auth/session').json()['token']
    invalid=client.post('/api/auth/login',json={'email':user['email'],'password':'wrong'})
    unknown=client.post('/api/auth/login',json={'email':'missing@example.test','password':'wrong'})
    assert invalid.status_code==unknown.status_code==401 and invalid.json()==unknown.json()
    response=client.post('/api/auth/login',json={'email':user['email'].upper(),'password':'Testing a long password 2026!'})
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=lax' in response.headers['set-cookie']
    assert client.cookies.get(auth.SESSION_COOKIE)!=session_cookie


def test_users_cannot_access_each_others_records(client):
    user=register(client)
    meeting=sample();meeting.update(id='private',owner_id=user['id'],status='ready',audio_file='uploads/private.wav',source='audio',stage='ready',progress=100)
    store.save(meeting)
    assert client.get('/api/meetings/private').status_code==200
    with TestClient(app,base_url='http://localhost') as other:
        second=register(other,email='other@example.test')
        assert second['id']!=user['id']
        assert other.get('/api/meetings').json()==[]
        assert other.get('/api/notifications').json()==[]
        for suffix in ('','/audio','/export/json','/export/pdf','/export/docx','/search?q=отчёт','/calendar','/agenda'):
            assert other.get('/api/meetings/private'+suffix).status_code==404
        assert other.delete('/api/meetings/private').status_code==404
        assert other.post('/api/meetings/private/retry').status_code==404
        assert other.post('/api/meetings/private/tasks',json={'title':'Взлом','evidence_ids':[1]}).status_code==404
        assert other.patch('/api/meetings/private/speakers/S1',json={'name':'Взлом'}).status_code==404
        assert cache.key_for('audio',meeting)!=cache.key_for('audio',{**meeting,'owner_id':second['id']})
    assert store.get('private')['owner_id']==user['id']


def test_csrf_origin_expiry_password_change(client):
    user=register(client)
    old_cookie=client.cookies.get(auth.SESSION_COOKIE)
    body={'current_password':'Testing a long password 2026!','new_password':'New long password 2026!'}
    assert client.post('/api/auth/password',json=body,headers={'X-CSRF-Token':'bad'}).status_code==403
    assert client.post('/api/auth/password',json=body,headers={'Origin':'https://evil.test'}).status_code==403
    assert client.post('/api/auth/password',json=body,headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    response=client.post('/api/auth/password',json=body)
    assert response.status_code==200
    with store.connect() as con:
        assert con.execute('SELECT 1 FROM sessions WHERE token_hash=?',(auth.digest(old_cookie),)).fetchone() is None
        con.execute('UPDATE sessions SET seen=?',(time.time()-auth.IDLE_TTL-1,))
    assert client.get('/api/meetings').status_code==401


def test_login_rate_limit(client):
    client.headers['X-CSRF-Token']=client.get('/api/auth/session').json()['token']
    for _ in range(10):
        assert client.post('/api/auth/login',json={'email':'unknown@example.test','password':'bad'}).status_code==401
    response=client.post('/api/auth/login',json={'email':'unknown@example.test','password':'bad'})
    assert response.status_code==429 and response.headers['retry-after']=='900'


def test_legacy_records_go_to_first_account_only(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);monkeypatch.setattr('app.main.DATA',tmp_path)
    store.init();item=sample();item.update(id='legacy',status='ready');store.save(item)
    with TestClient(app,base_url='http://localhost') as client:
        user=register(client,email='owner@example.test')
        assert store.get('legacy')['owner_id']==user['id']
        assert client.get('/api/meetings/legacy').status_code==200
        assert not (tmp_path/'setup-code.txt').exists()
        with TestClient(app,base_url='http://localhost') as other:
            register(other,email='second@example.test')
            assert other.get('/api/meetings/legacy').status_code==404


def test_registration_requires_matching_password_confirmation(client):
    client.headers['X-CSRF-Token']=client.get('/api/auth/session').json()['token']
    body={'email':'new@example.test','name':'New','password':'Long test password!'}
    assert client.post('/api/auth/register',json=body).status_code==422
    body['password_confirm']='Different password!'
    response=client.post('/api/auth/register',json=body)
    assert response.status_code==400 and response.json()['detail']=='Пароли не совпадают.'
    with store.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0


@pytest.mark.parametrize('provider',['google','facebook'])
def test_oauth_state_binding_replay_and_no_email_link(client,monkeypatch,provider):
    monkeypatch.setenv('DAUYS_'+provider.upper()+'_CLIENT_ID','configured-id')
    monkeypatch.setenv('DAUYS_'+provider.upper()+'_CLIENT_SECRET','configured-secret')
    local=register(client,email='same@example.test')
    client.post('/api/auth/logout')
    client.headers['X-CSRF-Token']=client.get('/api/auth/session').json()['token']
    started=client.post('/api/auth/oauth/'+provider+'/start').json()
    params=parse_qs(urlparse(started['url']).query)
    assert 'configured-secret' not in started['url']
    if provider=='google': assert params['code_challenge_method']==['S256']
    async def exchange(p,code,verifier):
        assert p==provider and code=='valid-code' and len(verifier)>30
        return 'provider-subject','OAuth person','same@example.test'
    monkeypatch.setattr(auth,'exchange_identity',exchange)
    url='/api/auth/oauth/'+provider+'/callback?'+urlencode_test(params['state'][0])
    with TestClient(app,base_url='http://localhost') as attacker:
        failed=attacker.get(url,follow_redirects=False)
        assert failed.headers['location'].endswith('oauth_failed')
    response=client.get(url,headers={'Sec-Fetch-Site':'cross-site'},follow_redirects=False)
    assert response.headers['location']=='/'
    session=client.get('/api/auth/session').json()
    assert session['user']['id']!=local['id'] and session['user']['provider']==provider
    replay=client.get(url,follow_redirects=False)
    assert replay.headers['location'].endswith('oauth_failed')


def urlencode_test(state):
    from urllib.parse import urlencode
    return urlencode({'state':state,'code':'valid-code'})


def test_disabled_provider_and_security_headers(client):
    client.headers['X-CSRF-Token']=client.get('/api/auth/session').json()['token']
    assert client.post('/api/auth/oauth/google/start').status_code==503
    assert client.get('/api/auth/session').headers['x-frame-options']=='DENY'
    assert 'frame-ancestors' in client.get('/').headers['content-security-policy']
    assert client.get('/data/setup-code.txt').status_code==404


@pytest.mark.parametrize('provider',['google','facebook'])
def test_oauth_token_exchange_uses_fixed_endpoints_and_server_secrets(monkeypatch,provider):
    monkeypatch.setenv('DAUYS_'+provider.upper()+'_CLIENT_ID','id')
    monkeypatch.setenv('DAUYS_'+provider.upper()+'_CLIENT_SECRET','secret')
    real_client=httpx.AsyncClient
    seen=[]
    def handle(request):
        seen.append(request)
        if request.method=='POST':
            fields=parse_qs(request.content.decode())
            assert fields['client_secret']==['secret'] and fields['code']==['one-use-code']
            if provider=='google': assert fields['code_verifier']==['verifier']
            return httpx.Response(200,json={'access_token':'provider-token'})
        assert request.headers['authorization']=='Bearer provider-token'
        if provider=='google':
            assert request.url.host=='openidconnect.googleapis.com'
            return httpx.Response(200,json={'sub':'stable-id','email_verified':True,'email':'a@b.test','name':'Person'})
        assert request.url.host=='graph.facebook.com' and request.url.params['appsecret_proof']
        return httpx.Response(200,json={'id':'stable-id','name':'Person'})
    monkeypatch.setattr(auth.httpx,'AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(handle),**kwargs))
    subject,name,email=asyncio.run(auth.exchange_identity(provider,'one-use-code','verifier'))
    assert subject=='stable-id' and name=='Person' and len(seen)==2
    assert (email is None) == (provider=='facebook')


def test_google_rejects_unverified_profile(monkeypatch):
    monkeypatch.setenv('DAUYS_GOOGLE_CLIENT_ID','id');monkeypatch.setenv('DAUYS_GOOGLE_CLIENT_SECRET','secret')
    real_client=httpx.AsyncClient
    def handle(request):
        return httpx.Response(200,json={'access_token':'token'} if request.method=='POST' else {'sub':'id','email_verified':False})
    monkeypatch.setattr(auth.httpx,'AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(handle),**kwargs))
    with pytest.raises(ValueError): asyncio.run(auth.exchange_identity('google','code','verifier'))


def test_secure_cookie_when_https_is_configured(client,monkeypatch):
    monkeypatch.setenv('DAUYS_PUBLIC_URL','https://localhost')
    response=client.get('/api/auth/session')
    assert 'Secure' in response.headers['set-cookie'] and 'HttpOnly' in response.headers['set-cookie']
