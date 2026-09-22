# HERMES Workspace Retrieval Specification
=============================================

**Engine:** `WorkspaceRetriever`  
**Date:** September 1, 2026  

---

## 1. Multi-Signal Scoring Architecture

| Signal | Weight | Description | Example |
|---|---|---|---|
| **Explicit Mention** | **10.0** | Filename or relative path explicitly mentioned in query | User says `auth.py` |
| **Filename Match** | **4.0** | Query keywords match file name or stem | `auth` matches `auth.py` |
| **AST Symbol Match**| **3.0** | Query keywords match class or function name | `authenticate` matches `def authenticate()` |
| **Path Match** | **2.0** | Query keywords match directory path | `backend` matches `backend/service.py` |
| **Test Pairing** | **3.5** | Automatically pairs test files with matched source | `auth.py` ➔ `test_auth.py` |
| **Dependency Expansion** | **2.5** | Pulls in directly imported local modules | `auth.py` ➔ `models.py` |

---

## 2. Context Assembly & Budget Constraints

Retrieved files and symbols are formatted into structured context:
```text
Relevant Workspace Files (2 retrieved):
 - module_0/auth.py (relevance: 23.0) | Symbols: AuthManager, AuthManager.authenticate
 - module_3/test_auth.py [TEST] (relevance: 7.0) | Symbols: test_auth
```
- Maximum files retrieved: Configurable (default 5).
- Maximum context tokens: Protected to prevent VRAM overflow.
