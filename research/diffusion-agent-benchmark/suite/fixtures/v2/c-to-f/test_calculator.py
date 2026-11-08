from calculator import c_to_f


def test_c_to_f():
    assert c_to_f(0)==32
    assert c_to_f(100)==212
    assert c_to_f(-40)==-40
