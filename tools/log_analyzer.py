import re


def count_by_level(lines: list[str]) -> dict[str, int]:
    """Counts occurrences of each log level extracted from log lines.
    Assumes log levels are inside brackets, e.g., '[INFO]', '[ERROR]'."""
    pattern = r'\[(.*?)\]'  # Regex pattern to match text inside brackets
    level_counts = {}
    for line in lines:
        matches = re.findall(pattern, line)
        for match in matches:
            level_counts[match] = level_counts.get(match, 0) + 1
    return level_counts


def filter_errors(lines: list[str]) -> list[str]:
    """Filters log lines to return only those containing '[ERROR]'."""
    error_lines = []
    for line in lines:
        if '[ERROR]' in line:
            error_lines.append(line)
    return error_lines