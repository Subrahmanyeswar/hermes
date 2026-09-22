from decimal import Decimal, getcontext
from typing import List

def add_decimals(a: float, b: float) -> Decimal:
    """Add two numbers using Decimal to avoid floating point errors."""
    return Decimal(str(a)) + Decimal(str(b))

def calculate_balance(transactions: List[float]) -> Decimal:
    """Calculate the balance from a list of transactions using Decimal for precision."""
    balance = Decimal('0.00')
    for transaction in transactions:
        balance = add_decimals(balance, transaction)
    return balance

if __name__ == "__main__":
    # Example usage
    transactions = [100.01, 50.00, 25.99]
    balance = calculate_balance(transactions)
    print(f"Balance: {balance}")