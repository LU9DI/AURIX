from calculator import unique_sorted


def test_unique_sorted():
    assert unique_sorted([3,1,3,2])==[1,2,3]
    assert unique_sorted([])==[]
