from calculator import absolute_value


def test_positive():
    assert absolute_value(7) == 7


def test_zero():
    assert absolute_value(0) == 0


def test_negative():
    assert absolute_value(-9) == 9
