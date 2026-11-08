from calculator import merge_dicts


def test_merge_dicts():
    a={'x':1}
    r=merge_dicts(a,{'y':2})
    assert r=={'x':1,'y':2}
    assert a=={'x':1}
    assert merge_dicts({'x':1},{'x':3})=={'x':3}
