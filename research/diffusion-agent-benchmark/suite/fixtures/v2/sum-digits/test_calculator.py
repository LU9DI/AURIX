from calculator import sum_digits


def test_sum_digits():
    assert sum_digits(123)==6
    assert sum_digits(0)==0
    assert sum_digits(-45)==9
