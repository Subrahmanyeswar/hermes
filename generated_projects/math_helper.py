# math_helper.py
# A module providing mathematical helper functions.

"""Math Helper Module
Functions:
- square(x): Return the square of x.
- cube(x): Return the cube of x.
"""

def square(x):
    """
    Return the square of x.
    
    Args:
        x: A number (int or float)
    
    Returns:
        The square of x
    
    Raises:
        TypeError: If x is not a number
    """
    if not isinstance(x, (int, float)):
        raise TypeError("x must be a number")
    return x * x

def cube(x):
    """
    Return the cube of x.
    
    Args:
        x: A number (int or float잎
    
    Returns:
        The cube of x
    
    Raises:
        TypeError: If x is not a number
    """
    if not isinstance(x, (int, float)):
        raise TypeError("x must be a number")
    return x ** 3