'''
string_helper.py - Helper functions for string manipulation.

Functions:
- reverse_string: Reverses a given string.
- is_palindrome: Checks if a string is a palindrome.
\nIncludes error handling for non-string inputs and tests for functionality.
'''

import re


def reverse_string(s):
    """
    Reverse a given string.
    
    Args:
        s (str): The input string to reverse.
    
    Returns:
        str: The reversed string.
    
    Raises:
        TypeError: If input is not a string.
    """
    if not isinstance(s, str):
        raise TypeError("Input must be a string")
    return s[::-1]


def is_palindrome(s):
    """
    Check if a given string is a palindrome.
    
    Args:
        s (str): The input string to check.
    
    Returns:
        bool: True if the string is a palindrome, False otherwise.
    
    Raises:
        TypeError: If input is not a string.
    """
    if not isinstance(s, str):
        raise TypeError("Input must be a string")
    # Clean the string by removing non-alphanumeric characters and converting to lowercase
    cleaned_string = re.sub(r'[^a-zA-Z0-9]', '', s).lower()
    return cleaned_string == cleaned_string[::-1]


def test_functions():
    """
    Test the reverse_string and is_palindrome functions with various inputs.
    """
    test_cases = [
        ("hello", "olleh", True),
        ("radar", "radar", True),
        ("hello world", "dlrow olleh", False),
        ("A man, a plan, a canal: Panama!", "amanaaplancanalpanama", True),
        ("12321", "12321", True),
        ("12345", "54321", False)
    ]
    
    print("Testing reverse_string:")
    for original, expected, _ in test_cases:
        result = reverse_string(original)
        print(f"Original: {original}, Reversed: {result}")
        assert result == expected, f"Test failed for reverse_string with input {original}"
    
    print("\nTesting is_palindrome:")
    for original, _, expected in test_cases:
        result = is_palindrome(original)
        print(f"String: {original}, Is palindrome: {result}")
        assert result == expected, f"Test failed for is_palindrome with input {original}
"    
if __name__ == "__main__":
    test_functions()
