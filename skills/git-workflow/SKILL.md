---
name: git-workflow
description: Safe Git version control workflows, atomic commits, repository inspection, and non-destructive operations
triggers: [git, github, commit, push, pull request, branch, repository, repo, version control]
priority: 1
max_tokens: 450
---

# Git Workflow Specialist

Apply these strict, non-destructive safety rules for all Git operations.

## 1. Non-Negotiable Safety Invariants
1. **Never Re-Initialize:** Never run `git init` in an existing repository or workspace unless explicitly instructed to create a new repository from scratch.
2. **Never Execute Destructive Commands:** Under no circumstances execute destructive commands such as `git reset --hard`, `git clean -fdx`, `git checkout -- .`, or `git restore .`. These will erase uncommitted user work.
3. **Explicit User Authorization:** Never create a Git commit or push to a remote repository without explicit user instructions requesting the commit or push.
4. **Targeted Staging Only:** Never use `git add -A` or `git add .` indiscriminately. Always stage only the specific files modified as part of the authorized task.

## 2. Standard Safe Workflow
5. **Inspect Status First:**
   - Always run `git status` via `shell.bash` before staging or committing to understand tracked, untracked, and modified files.
   - Run `git diff` to review exact changes and ensure unrelated files or sensitive credentials (`.env`, secrets, cache directories) are not touched.
6. **Verify Environment & Configuration:**
   - Ensure appropriate `.gitignore` rules exist for language-specific artifacts (`__pycache__/`, `node_modules/`, `.env`, build outputs).
   - Inspect the current branch with `git branch --show-current`. Do not assume `main` or overwrite current branch topology.
7. **Atomic Commits:**
   - Group coherent changes into logical commits.
   - Use standard conventional commit messages: `feat: ...`, `fix: ...`, `docs: ...`, `test: ...`, `refactor: ...`.
8. **Remote Operations:**
   - Push to remotes *only* after explicit confirmation and verification of the target remote URL (`git remote -v`).
   - For complete safety guidelines and failure recovery protocols, refer to `references/safety_rules.md`.
