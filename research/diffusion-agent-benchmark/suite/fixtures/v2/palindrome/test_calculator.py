from calculator import is_palindrome


def test_is_palindrome():
    assert is_palindrome('A man, a plan, a canal: Panama')
    assert not is_palindrome('hello')
    assert is_palindrome('')
