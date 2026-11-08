from calculator import fizzbuzz


def test_fizzbuzz():
    assert fizzbuzz(15)=='FizzBuzz'
    assert fizzbuzz(9)=='Fizz'
    assert fizzbuzz(10)=='Buzz'
    assert fizzbuzz(7)=='7'
