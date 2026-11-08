from calculator import average


def test_average():
    assert average([1,2])==1.5
    assert average([])==0.0
    assert average([4])==4
