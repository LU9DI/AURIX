from calculator import is_even


def test_even_positive():
    assert is_even(4) is True


def test_odd_positive():
    assert is_even(5) is False


def test_even_negative():
    assert is_even(-8) is True


def test_zero():
    assert is_even(0) is True
