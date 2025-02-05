def test_user_preferences():
    assert validate_user_preferences({"theme": "dark", "notifications": True}) == True
    assert validate_user_preferences({"theme": "light", "notifications": False}) == True
    assert validate_user_preferences({"theme": "invalid_theme", "notifications": True}) == False
    assert validate_user_preferences({"theme": "dark"}) == False
    assert validate_user_preferences({"notifications": "yes"}) == False