import re
import shlex

def split_compound_command(cmd: str):
    """
    Tokenizes a command string into a list of (subcommand, operator) pairs.
    Handles quotes (single and double) so && or ; inside quotes are not treated as operators.
    Operators recognized: '&&', '||', '|', '&', ';'
    """
    operators = ['&&', '||', '|', '&', ';']
    tokens = []
    current = []
    in_single = False
    in_double = False
    i = 0
    n = len(cmd)

    while i < n:
        c = cmd[i]
        if c == "'" and not in_double:
            in_single = not in_single
            current.append(c)
            i += 1
        elif c == '"' and not in_single:
            in_double = not in_double
            current.append(c)
            i += 1
        elif not in_single and not in_double:
            # Check 2-char operators first
            op2 = cmd[i:i+2]
            if op2 in ('&&', '||'):
                tokens.append((''.join(current).strip(), op2))
                current = []
                i += 2
                continue
            # Check 1-char operators
            if c in ('|', '&', ';'):
                # map ';' to '&' on Windows
                tokens.append((''.join(current).strip(), c))
                current = []
                i += 1
                continue
            current.append(c)
            i += 1
        else:
            current.append(c)
            i += 1

    if current or not tokens:
        tokens.append((''.join(current).strip(), ''))

    return tokens

# Test cases
test_cases = [
    'pwd && ls -la && echo "---NODE---" && node --version 2>/dev/null',
    'echo "hello && world" && pwd',
    'cd "C:\\Users\\SUBBU\\Downloads\\rocket4 hermes test" && dir /a && echo "---" && ls -la',
    'dir /a:h .hermes .artifacts 2>&1 | head -50',
    'pwd; ls; whoami'
]

for tc in test_cases:
    print(f"INPUT: {tc}")
    parts = split_compound_command(tc)
    for subcmd, op in parts:
        print(f"  [{subcmd}] -> op: '{op}'")
    print()
