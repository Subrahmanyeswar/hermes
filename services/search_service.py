def case_insensitive_search(query, items):
    """
    Perform a case-insensitive search on a list of items.
    
极高
    Args:
        query (str): The search query string.
        items (list): List of strings to search through.
    
    Returns:
        list: List of items that match the query case-insensitively.
    """
    if not isinstance(items, list):
        raise ValueError("Items must be a list")
    query_lower = query.lower()
    return [item for item in items if item.lower() == query_lower]

# Example usage (for testing purposes):
if __name__ == "__main__":
    items = ["Apple", "banana", "Orange", "apple"]
    query = "apple"
    results = case_insensitive_search(query, items)
    print("Matched items:", results)