from calculator import strip_prefix


def test_strip_prefix():
    assert strip_prefix('foobar','foo')=='bar'
    assert strip_prefix('aab','a')=='ab'
    assert strip_prefix('xyz','q')=='xyz'
