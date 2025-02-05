def test_input_validation():
    assert validate_input("valid_input") == True
    assert validate_input("") == False
    assert validate_input("invalid_input!") == False
    assert validate_input("another_valid_input") == True