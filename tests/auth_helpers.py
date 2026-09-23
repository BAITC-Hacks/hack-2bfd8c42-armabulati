def register(client, email='tester@example.test', name='Тест'):
    client.headers['X-CSRF-Token'] = client.get('/api/auth/session').json()['token']
    response = client.post('/api/auth/register', json={'name':name,'email':email,'password':'Testing a long password 2026!', 'password_confirm':'Testing a long password 2026!'})
    assert response.status_code == 201, response.text
    client.headers['X-CSRF-Token'] = response.json()['token']
    return response.json()['user']
