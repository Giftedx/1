def test_health_check():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}