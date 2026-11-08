from calculator import binary_search


def test_binary_search():
    xs=[1,3,5,7,9]
    assert [binary_search(xs,v) for v in xs]==[0,1,2,3,4]
    assert binary_search(xs,4)==-1
    assert binary_search([],1)==-1
