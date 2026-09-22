def is_prime(n: int) -> bool:

    """

    Check if a number is prime.

    Args:

        n (int): The number to check.

    Returns:

        bool: True if n is prime and >= 2, False otherwise.

    """

    if n < 2:

        return False

    if n == 2:

        return True

    if n % 2 == 0:

        return False

    i = 3

    while i * i <= n:

        if n % i == 0:

            return False

        i += 2

    return True