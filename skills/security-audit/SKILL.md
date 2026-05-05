---
name: security-audit
description: Security review checklist based on OWASP Top 10 for Python web applications
triggers: [security, vulnerability, audit, injection, xss, sanitise, owasp, secure, exploit]
priority: 1
max_tokens: 300
---
# Security Audit Specialist
Apply all checks before marking any code as complete.
## Input Validation
1. Never trust user input — validate all request parameters with type checks and length limits
2. SQL injection: never concatenate user input into SQL strings — use parameterised queries
3. XSS: escape all user-supplied data before rendering in HTML templates
## Authentication
4. Never store plain-text passwords — use bcrypt or argon2 via passlib
5. JWT secrets must come from environment variables, min 32 characters, random
6. Session tokens must be cryptographically random — use secrets.token_hex(32)
## File Operations
7. Never use user-supplied filenames directly — sanitise with os.path.basename()
8. Reject file paths containing ../ — path traversal attack vector
## Environment
9. API keys and secrets must be in .env — never in source code
10. .env must be in .gitignore — verify before first commit
## Code Review Checklist
11. Check for: hardcoded credentials, eval() usage, pickle.loads() on untrusted data, subprocess with shell=True and user input
