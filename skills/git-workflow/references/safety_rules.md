# Git Safety Rules and Recovery Protocols

This document details mandatory safety invariants when performing version control operations in HERMES workspaces.

## 1. Prohibited Commands in Agent Execution
The following commands are classified as destructive and are strictly prohibited in automated or unverified agent operations:
- `git reset --hard` (destroys uncommitted changes and uncommitted worktree state)
- `git clean -f` / `git clean -fdx` (permanently deletes untracked files)
- `git checkout -f` (discards local modifications)
- `git push --force` / `git push -f` (destroys remote repository history)
- `git rebase` on shared or production branches

## 2. Safe Inspection Protocols
Before any staging or mutation, execute read-only diagnostic commands:
```bash
git status --short
git diff --stat
git branch -vv
git remote -v
```

## 3. Targeted Staging Protocol
Always stage explicitly by relative path:
```bash
# Correct: Stage only the specific target file
git add path/to/changed_file.py

# Incorrect / Forbidden:
git add .
git add -A
```

## 4. Recovering from Accidental Staging
If a file was staged inadvertently, unstage it without altering worktree contents:
```bash
git restore --staged <file>
# Or in older Git versions:
git reset HEAD <file>
```
