with open("core/evidence/models.py", "r", encoding="utf-8") as f:
    content = f.read()

target = 'class EvidenceSourceType(str, Enum):\n    FILE_EXISTENCE = "FILE_EXISTENCE"'
replacement = '''class EvidenceSourceType(str, Enum):
    # Distinct Evidence Provenance Types (Phase E)
    INPUT_DISCOVERY = "INPUT_DISCOVERY"
    ARTIFACT_WRITE = "ARTIFACT_WRITE"
    ARTIFACT_PROMOTION = "ARTIFACT_PROMOTION"
    SYNTAX_VALIDATION = "SYNTAX_VALIDATION"
    CONTRACT_VALIDATION = "CONTRACT_VALIDATION"
    API_TEST = "API_TEST"
    RUNTIME_TEST = "RUNTIME_TEST"
    BROWSER_TEST = "BROWSER_TEST"

    # Existing source types
    FILE_EXISTENCE = "FILE_EXISTENCE"'''

content_norm = content.replace("\r\n", "\n")
if target in content_norm:
    content_norm = content_norm.replace(target, replacement, 1)
    with open("core/evidence/models.py", "w", encoding="utf-8") as f:
        f.write(content_norm)
    print("Updated core/evidence/models.py successfully!")
else:
    print("Target not found!")
