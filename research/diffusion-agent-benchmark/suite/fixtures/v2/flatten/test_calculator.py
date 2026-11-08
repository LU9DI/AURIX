from calculator import flatten


def test_flatten():
    assert flatten([[1,2],[3]])==[1,2,3]
    assert flatten([])==[]
    assert flatten([[],[4]])==[4]
