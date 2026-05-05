---
name: git-workflow
description: Git and GitHub workflow patterns for committing, branching, and pushing code
triggers: [git, github, commit, push, pull request, branch, repository, repo, version control]
priority: 1
max_tokens: 300
---
# Git Workflow Specialist
Apply these rules exactly for all git operations.
## Initialisation
1. Always run git_init before any git_add_commit call
2. Create a .gitignore before first commit: include __pycache__/, .env, venv/, data/
## Committing
3. Commit message format: "type: short description" — types: feat, fix, docs, refactor, test
4. Always stage all changes with add_all=True unless told otherwise
5. Never commit .env files, API keys, or credentials
## Pushing to GitHub
6. Use git_push tool only after at least one successful git_add_commit
7. GITHUB_TOKEN must be set as environment variable — never hardcode it
8. Always verify the remote URL contains github.com before pushing
## Branch Strategy
9. Default branch: main
10. Feature branches: feature/description, bug fix: fix/description
## File Creation Order for a New Project
11. Create all project files → git_init → git_add_commit → git_push
