from calculator import max_of


def test_max_of():
    assert max_of([1,5,3])==5
    assert max_of([-4,-2,-9])==-2
