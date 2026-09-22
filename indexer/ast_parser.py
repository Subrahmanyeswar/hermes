import ast


def parse_ast(code):
    """
    Parse the given Python code and return a list of function and class names.
    
    Args:
        code (str): Python code as a string.
    
    Returns:
        list: List of symbol names (function and class names).
    """
    try:
        module = ast.parse(code)
        symbols = []
        for node in ast.walk(module):
            if isinstance(node, ast.FunctionDef):
                symbols.append(node.name)
            elif isinstance(node, ast.ClassDef):
                symbols.append(node.name)
        return symbols
    except Exception as e:
        print(f"Error parsing AST: {e}")
        return []