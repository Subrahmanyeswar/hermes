# OWASP Top 10 Security Assessment Checklist

This reference outlines verification criteria for the standard OWASP Top 10 web application security risks.

## A01: Broken Access Control
- Verify authorization checks exist on every protected endpoint and function.
- Ensure users cannot access or mutate resources belonging to other tenants by manipulating IDs in URLs or request payloads (IDOR).
- Confirm CORS headers restrict origin access appropriately.

## A02: Cryptographic Failures
- Verify sensitive data in transit is encrypted using TLS/HTTPS.
- Ensure passwords are stored using salted key derivation functions (Argon2id, bcrypt, PBKDF2).
- Check that legacy/broken algorithms (MD5, SHA1, DES) are not used for security decisions.

## A03: Injection
- Check that all database access uses parameter binding.
- Verify shell invocations pass separate argument lists without shell interpolation.
- Check ORM queries for raw SQL clauses with unescaped parameters.

## A04: Insecure Design
- Review threat model: rate limiting on login/registration endpoints, lockout policies on repeated failures.
- Verify defense in depth: validate inputs at API gateways, application controllers, and database layers.

## A05: Security Misconfiguration
- Ensure default credentials and debug modes (e.g. `DEBUG = True` in Flask/Django) are disabled in production configurations.
- Verify security headers: `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`.

## A06: Vulnerable and Outdated Components
- Review dependencies in `requirements.txt` or `package.json` for known CVEs.
- Avoid pinning deprecated or unmaintained third-party packages.

## A07: Identification and Authentication Failures
- Confirm session timeouts and token expiration are configured.
- Ensure session identifiers are rotated upon successful authentication.

## A08: Software and Data Integrity Failures
- Never deserialize untrusted data with Python `pickle`, `yaml.load` (without SafeLoader), or Java serialization.
- Verify integrity of third-party assets and scripts via subresource integrity (SRI) hashes.

## A09: Security Logging and Monitoring Failures
- Ensure security events (authentication failures, permission denials) are logged without logging sensitive data (passwords, auth tokens).

## A10: Server-Side Request Forgery (SSRF)
- If the application fetches remote URLs on behalf of users, validate the destination host against an explicit allowlist and block requests to internal networks (e.g. `127.0.0.1`, `169.254.169.254`).
