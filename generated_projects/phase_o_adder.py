def add(a, b):
    """
    Add two numbers and return the result.
    
    Args:
        a (int/float): First number
        b (int/float): Second number
    
    Returns:
        int/float: Sum of a and b
    
    Raises:
        TypeError: If inputs are not numbers
    """
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        raise TypeError("Both arguments must be numbers")
    return a + b

# Example usage
if __name__ == "__main__":
    print(add(5, 3))  # Output: 8
    print(add(10.5, 2.3))  # Output: 12.8