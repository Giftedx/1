def test_route_health_check(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json == {'status': 'healthy'}

def test_route_example(client):
    response = client.get('/example')
    assert response.status_code == 200
    assert 'data' in response.json

def test_route_not_found(client):
    response = client.get('/nonexistent')
    assert response.status_code == 404