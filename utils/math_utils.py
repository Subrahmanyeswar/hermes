def clamp(val: float, min_val: float, max_val: float) -> float:
    """
    Clamp the value between min_val and max_val.
    
    Args:
        val (float): The value to clamp.
        min_val (float): The minimum value.
        max_val (float): The maximum value.
    
    Returns:
        float: The clamped value.
    
    Raises:
        ValueError: If min_val > max_val.
    """
    if min_val > max_val:
        raise ValueError("min_val must be less than or equal to max_val")
    return max(min_val, min(val, max_val))