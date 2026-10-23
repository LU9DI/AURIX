from calculator import gcd


def test_gcd():
    assert gcd(12,18)==6
    assert gcd(7,13)==1
    assert gcd(9,0)==9
