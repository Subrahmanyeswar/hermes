def apply_discount(price: float, discount_pct: float) -> float:
    """
    Calculate the discounted price.
    
    Args:
        price (float): The original price.
        discount_pct (float): The discount percentage (e.g., 10 for 10%).
    
    Returns:
        float: The price after discount.
    """
    return price * (1.0 - discount_pct / 100.0)

if __name__ == "__main__":
    # Example test
    price = 100.0
    discount = 20.0
    discounted_price = apply_discount(price, discount)
    print(f"Original price: {price}, Discounted price: {discounted_price}")