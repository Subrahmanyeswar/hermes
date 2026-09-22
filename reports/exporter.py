import json
from dataclasses import dataclass
from typing import List

@dataclass
class Report:
    id: int
    name: str
    date: str


def export_to_json(reports: List[Report]) -> str:
    """
    Serialize a list of Report objects to a JSON string.
    
    Args:
        reports: List of Report objects to serialize
    
    Returns:
        JSON string representation
    """
    report_dicts = [vars(report) for report in reports]
    return json.dumps(report_dicts, indent=4)

if __name__ == "__main__":
    # Example usage for testing
    reports = [Report(id=1, name="Test Report", date="2023-01-01")]
    json_output = export_to_json(reports)
    print(json_output)