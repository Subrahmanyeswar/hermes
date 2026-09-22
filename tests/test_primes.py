import pytest
from math_tools.primes import is_prime

test_cases = [
    (2, True),
    (3, True),
    (5, True),
    (7, True),
    (11, True),
    (13, True),
    (17, True),
    (-5, False),
    (0, False),
    (1, False),
    (4, False),
    (6, False),
    (8, False),
    (9, False)
]

@pytest.mark.parametrize('n, expected', test_cases)
def test_is_prime(n, expected):
    assert is_prime(n) == expected