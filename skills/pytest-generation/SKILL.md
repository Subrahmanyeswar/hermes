---
name: pytest-generation
description: Generate comprehensive, robust pytest test suites covering functional behavior, edge cases, fixtures, and failure modes
triggers: [pytest, tests, test, unit test, unit tests, write tests, test cases, test suite, testing, test coverage, test file, edge cases]
priority: 1
max_tokens: 450
---

# Pytest Generation Specialist

Apply these engineering principles to generate high-value, maintainable pytest test suites.

## 1. Code Inspection & Contract Analysis
1. Read the implementation module using `fs.read` before authoring tests.
2. Identify public interfaces, expected return types, preconditions, error handling, and side effects.
3. Align test style (class-based `TestX` or standalone `test_x` functions) with the existing repository conventions.

## 2. Test Coverage Dimensions
4. **Happy Path:** Verify standard valid inputs produce expected return values or state changes.
5. **Edge Cases & Boundaries:**
   - Empty collections (`[]`, `{}`), empty strings (`""`), zero, negative numbers.
   - Boundary limits (minimum/maximum integer or date boundaries).
   - Unicode, whitespace, and special characters where relevant.
6. **Exception & Error Handling:**
   - Test invalid inputs using `pytest.raises(ExpectedException)`.
   - Verify specific exception messages or error codes when contracts require them (`pytest.raises(ValueError, match=r"...")`).
7. **Parametrization:**
   - Use `@pytest.mark.parametrize` for table-driven testing across multiple related input/output combinations.

## 3. Test Isolation & Fixtures
8. **Filesystem Isolation:** Always use the built-in `tmp_path` fixture for any test requiring disk reads or writes. Never create temporary files directly in the repository root.
9. **Mocks & Spies:** Use `monkeypatch` or `unittest.mock` to isolate external I/O (network requests, third-party APIs, clock calls). Keep mocks minimal and faithful to actual API behavior.

## 4. Test Execution & Verification
10. Write test files to `tests/test_{module_name}.py` using `fs.write` (or `fs.edit`).
11. Execute tests via `shell.bash` using the project's canonical Python virtual environment:
    ```bash
    python -m pytest tests/test_target.py -v
    ```
12. Verify test outcomes: Ensure newly authored tests pass and that failures represent real defects in the code under test rather than flawed test logic.
