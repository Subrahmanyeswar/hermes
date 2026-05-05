---
name: bash-scripting
description: Bash scripting best practices, error handling, and safe shell command patterns
triggers: [bash, shell script, linux, terminal, command line, automation, shell, cron, sh file]
priority: 1
max_tokens: 300
---
# Bash Scripting Specialist
Apply these rules for all shell scripts and bash commands.
## Script Header (always include)
1. First line: #!/bin/bash
2. Second line: set -euo pipefail  (exit on error, undefined vars, pipe failures)
3. Third line: Script description as comment
## Variables and Quoting
4. Always quote variables: "$variable" not $variable
5. Use ${variable:-default} for variables that might be empty
6. Declare constants with readonly: readonly CONFIG_FILE="/etc/app/config"
## Error Handling
7. Check exit codes: command || { echo "command failed"; exit 1; }
8. Use trap for cleanup: trap 'rm -f /tmp/tempfile' EXIT
## Safety Rules
9. Never use rm -rf with variables — always use absolute paths
10. Validate that required files/directories exist before operating on them
11. Use mktemp for temporary files: TMPFILE=$(mktemp)
## Argument Parsing
12. Use getopts for flags, positional args with $1, $2 etc for required params
13. Always print usage when --help or -h is passed
