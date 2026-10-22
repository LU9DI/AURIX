from calculator import add


def test_add_positive_numbers():
    assert add(2, 3) == 5


def test_add_negative_number():
    assert add(-2, 3) == 1


def test_add_zero():
    assert add(0, 0) == 0
