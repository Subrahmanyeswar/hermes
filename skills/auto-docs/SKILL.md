---
name: auto-docs
description: Generate README files, docstrings, and API documentation from existing code
triggers: [docs, documentation, readme, docstring, api docs, document, explain code, jsdoc]
priority: 1
max_tokens: 300
---
# Documentation Generation Specialist
Follow these rules for all documentation tasks.
## README.md Structure (always use this order)
1. Project name and one-sentence description
2. Features list (bullet points, max 8 items)
3. Prerequisites (Python version, dependencies)
4. Installation steps (numbered)
5. Usage examples with code blocks
6. Configuration table (env vars and their purpose)
7. License
## Docstring Format (Google style)
8. Every public function needs: one-line summary, Args section, Returns section, Raises section if applicable
9. Example: def add(a: int, b: int) -> int:\n    """Add two integers.\n    Args:\n        a: First integer.\n        b: Second integer.\n    Returns:\n        Sum of a and b.\n    """
## Reading Code Before Documenting
10. Always use read_file to read the module first
11. Use list_directory to understand project structure before writing README
## Output
12. Use write_file to create docs — never print documentation to chat
13. README.md goes in the project root
