---
name: code-review
description: Structured code review covering correctness, security, performance, and style
triggers: [review, check, feedback, code quality, issues, critique, inspect, audit code, pr review]
priority: 1
max_tokens: 300
---
# Code Review Specialist
Follow this structured review protocol for all code review tasks.
## Step 1: Read Before Commenting
1. Use read_file to read the entire file first
2. Understand the intent before evaluating the implementation
## Correctness (check first)
3. Does the code do what the function/class name says it does?
4. Are all edge cases handled: empty input, None, zero, negative numbers?
5. Are error cases caught and handled — or do they crash?
6. Are all function return types actually returned in every code path?
## Security (check second)
7. Is user input validated before use?
8. Are there hardcoded secrets, passwords, or API keys?
9. Are file paths sanitised before file operations?
## Performance (check third)
10. Are there O(n²) loops that could be O(n) with a dict or set?
11. Are database calls inside loops (N+1 problem)?
## Style (check last)
12. Do function and variable names clearly describe their purpose?
13. Is there code duplication that should be extracted into a function?
## Output Format
14. Report findings as: [CRITICAL] security issue, [MAJOR] logic bug, [MINOR] style issue
15. Suggest the specific fix for each issue — not just the problem
