import sys

def closed_range(start, end):
    """
    Generate a closed range from start to end inclusive.
    
    Args:
        start (int): Start index.
        end (int): End index, inclusive.
    
    Returns:
        list: List of integers from start to end.
    
    Raises:
        TypeError: If start or end is not an integer.
        ValueError: If start > end.
    """
    
    if not isinstance(start, int) and not isinstance(end, int):
        raise TypeError("Both start and end must be integers.")
    
    if start > end:
        raise ValueError("Start cannot be greater than end.")
    
    return list(range(start, end+1))

if __name__ == "__main__":
    # Example usage
    print(closed_range(1, 5))  # [1,2,3,4,5]
    
    # Test with negative
    print(closed_range(-5, -1))  # [-5,-4,-3,-2,-1]