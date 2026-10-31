---
name: bash-scripting
description: Shell scripting best practices, robust error handling, portability, and safe command execution
triggers: [bash, shell script, linux, terminal, command line, automation, shell, cron, sh file]
priority: 1
max_tokens: 450
---

# Bash & Shell Scripting Specialist

Apply these production-grade principles for all shell scripts, automation tasks, and command sequences.

## 1. Environment & Shell Identification
1. Determine the target execution environment:
   - Bash scripts: Use `#!/usr/bin/env bash` with `set -euo pipefail`.
   - POSIX `sh` scripts: Use `#!/bin/sh` with `set -eu` (avoid Bash-specific arrays, `[[ ]]`, and `pipefail`).
   - Windows environments: If executing under Windows PowerShell or cmd, use native PowerShell idioms or WSL rather than assuming POSIX utilities.

## 2. Defensive Coding & Error Handling
2. **Quoting:** Always quote variables and command substitutions: `"$variable"`, `"$(command)"`. Never leave expansions unquoted in arguments or paths.
3. **Default Values:** Use parameter expansion for optional variables: `${VAR:-default_value}` or `${VAR:?error message if unset}`.
4. **Exit Codes & Traps:**
   - Always verify command outcomes: `command || { echo "error message" >&2; exit 1; }`.
   - Temporary file cleanup: Always bind `trap` to the specific file created by `mktemp`:
     ```bash
     TMPFILE="$(mktemp)" || exit 1
     trap 'rm -f "$TMPFILE"' EXIT
     ```
   - Never use generic wildcards in traps or cleanup handlers.

## 3. Safety Boundaries
5. **Destructive Commands:**
   - Never run `rm -rf` against unvetted variables or relative paths without explicit directory verification.
   - Never execute destructive Git commands (`git reset --hard`, `git clean -fdx`).
   - Validate that target directories exist before running file operations (`[ -d "$TARGET_DIR" ]`).

## 4. Argument Parsing & CLI Standards
6. Use `getopts` for short options (`-h`, `-v`, `-f file`) and validate mandatory arguments before execution.
7. Always provide a `--help` / `-h` usage function outlining expected arguments, flags, and exit codes.
8. Output diagnostics and errors to `stderr` (`>&2`), reserving `stdout` for pipeline data.
