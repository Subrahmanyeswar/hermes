import datetime

def format_iso_utc(dt: datetime.datetime) -> str:
    """
    Format a datetime object to ISO 8601 string ensuring UTC representation.
    If the datetime is naive, it is treated as UTC.
    Args:
        dt: The datetime object to format.
    Returns:
        str: The ISO formatted string with UTC offset or 'Z'.
    Raises:
        ValueError: If dt is not a datetime object.
    """
    if not isinstance(dt, datetime.datetime):
        raise ValueError("Input must be a datetime object")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.isoformat()
