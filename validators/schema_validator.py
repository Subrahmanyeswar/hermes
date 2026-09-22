import json
def validate(data, schema):
    """
    Validate JSON data against a given schema.
    
    Args:
        data: The JSON data to validate (as a Python dict).
        schema: A dictionary containing validation rules, e.g.,
                {"type": "string", "required": ["name"], "properties": {"age": {"type": "number", "minimum": 18}}, "minimum": 0, "maximum": 100}
    
    Raises:
        ValueError: If type, minimum, or maximum constraints are violated.
        KeyError: If required fields are missing.
    
    Returns:
        True if validation passes.
    """
    # If schema is empty, return True
    if not schema:
        return True

    # Check type if specified
    if 'type' in schema:
        type_str = schema['type']
        if type_str == 'string':
            if not isinstance(data, str):
                raise ValueError(f"Expected string, got {type(data)}")
        elif type_str == 'number':
            if not isinstance(data, (int, float)):
                raise ValueError(f"Expected number, got {type(data)}")
        elif type_str == 'boolean':
            if not isinstance(data, bool):
                raise ValueError(f"Expected boolean, got {type(data)}")
        elif type_str == 'object':
            if not isinstance(data, dict):
                raise ValueError(f"Expected object, got {type(data)}")
        elif type_str == 'array':
            if not isinstance(data, list):
                raise ValueError(f"Expected array, got {type(data)}")
        else:
            raise ValueError(f"Unsupported type: {type_str}")

    # Handle required fields
    if 'required' in schema:
        for field in schema['required']:
            if field not in data:
                raise KeyError(f"Missing required field: {field}")

    # Handle properties (for objects)
    if 'properties' in schema:
        for field, sub_schema in schema['properties'].items():
            if field in data:
                # Only validate if the field exists
                validate(data[field], sub_schema)

    # Handle minimum and maximum (for numbers)
    if 'minimum' in schema and isinstance(data, (int, float)):
        if data < schema['minimum']:
            raise ValueError(f"Value below minimum: {data} < {schema['minimum']}")
㎧
    if 'maximum' in schema and isinstance(data, (int, float)):
        if data > schema['maximum']:
            raise ValueError(f"Value above maximum: {data} > {schema['maximum']}")

    return True