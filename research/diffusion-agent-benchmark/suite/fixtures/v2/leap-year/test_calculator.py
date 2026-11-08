from calculator import is_leap


def test_is_leap():
    assert is_leap(2024)
    assert not is_leap(1900)
    assert is_leap(2000)
    assert not is_leap(2023)
