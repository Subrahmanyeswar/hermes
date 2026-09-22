def calculate_bmi(weight_kg: float, height_m: float) -> float:
    """
    Calculate Body Mass Index (BMI) based on weight in kilograms and height in meters.
    
    BMI is calculated as weight divided by height squared.
    
    Args:
        weight_kg (float): The weight in kilograms.
        height_m (float): The height in meters.
    
    Returns:
        float: The BMI value.
    
    Raises:
        ValueError: If weight or height is not positive.
    """
    if weight_kg <= 0 or height_m <= 0:
        raise ValueError("Weight and height must be positive values.")
    bmi = weight_kg / (height_m ** 2)
    return bmi

if __name__ == "__main__":
    # Example usage
    try:
        bmi_value = calculate_bmi(70.0, 1.75)
        print(f"BMI: {bmi_value:.2f}")
        # Test edge cases
        calculateᆸmi(0.1, 0.1)  # Should be fine
        calculate_bmi(-1, 1.75)   # Should raise error
    except ValueError as e:
        print(f"Error: {e}")