---
name: security-audit
description: Application security review, vulnerability assessment, threat modeling, and OWASP Top 10 mitigation
triggers: [security, vulnerability, audit, injection, xss, sanitise, owasp, secure, exploit]
priority: 1
max_tokens: 450
---

# Security Audit Specialist

Apply these rigorous, evidence-driven security practices to evaluate application code and configuration for vulnerabilities.

## 1. Audit Principles & Non-Destructive Boundary
1. Perform static code analysis and architectural reviews using `fs.read` and `search.grep`.
2. Do not execute invasive penetration tests, brute-force exploits, or external attacks against remote services.
3. Differentiate verified vulnerabilities (supported by reproducible code paths) from theoretical security hardening recommendations.

## 2. Core Attack Surfaces & Vulnerability Classes

### A. Injection Flaws
- **SQL Injection:** Ensure all database queries use parameterised queries or ORM abstractions. Never interpolate strings or user input directly into SQL statements.
- **Command Injection:** Avoid `subprocess.run(..., shell=True)` with user-supplied arguments. Use explicit argument lists (`shell=False`).
- **Template Injection / XSS:** Ensure user input rendered in HTML templates is properly escaped. In frontend JavaScript, never pass unsanitized input to `innerHTML`.

### B. Authentication & Session Management
- Passwords must be hashed using robust algorithms (bcrypt, Argon2, PBKDF2). Never store plain-text or reversibly encrypted passwords.
- Secret keys and JWT signing secrets must be cryptographically random and stored in environment variables, never hardcoded in source control.
- Ensure authentication tokens and session identifiers are invalidated upon logout.

### C. File & Path Operations (Path Traversal)
- Validate and sanitize all user-controlled file paths. Ensure resolved paths remain strictly within the authorized workspace directory.
- Reject paths containing directory traversal tokens (`../`, `..\\`).

### D. Sensitive Data & Secrets Exposure
- Inspect source code and version control for committed API keys, tokens, database credentials, or private certificates.
- Ensure `.env` and credential files are included in `.gitignore`.

## 3. Structured Security Reporting
Report every finding using this format:
- **Severity:** `[CRITICAL]` (Remote code execution, SQLi, authentication bypass), `[HIGH]` (Privilege escalation, stored XSS), `[MEDIUM]` (Information disclosure, missing CSRF), `[LOW]` (Security hardening recommendation).
- **Location:** File path and specific lines.
- **Vulnerability Description & Impact:** Mechanism of exposure and potential attacker impact.
- **Remediation:** Specific code correction or configuration change.
- For detailed OWASP Top 10 checklists, see `references/owasp_checklist.md`.
