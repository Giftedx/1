def test_exception_handling():
    with pytest.raises(ValueError):
        raise ValueError("This is a test exception")

    with pytest.raises(IndexError):
        my_list = []
        my_list[1]  # This will raise an IndexError

    with pytest.raises(KeyError):
        my_dict = {}
        my_dict['non_existent_key']  # This will raise a KeyError

    assert True  # Ensure the test runs to completion without unhandled exceptions