from calculator import count_vowels


def test_count_vowels():
    assert count_vowels('Education')==5
    assert count_vowels('xyz')==0
    assert count_vowels('AEIOU')==5
