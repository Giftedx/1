def test_rate_limiter():
    assert rate_limiter(5, 1) == True
    assert rate_limiter(0, 1) == False
    assert rate_limiter(5, 0) == False
    assert rate_limiter(10, 2) == True
    assert rate_limiter(10, 5) == False