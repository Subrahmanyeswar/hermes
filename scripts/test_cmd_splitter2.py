def split_compound_command(cmd: str):
    """
    Tokenizes a command string into a list of (subcommand, operator) pairs.
    Handles quotes (single and double) so && or ; inside quotes are not treated as operators.
    Operators recognized: '&&', '||', '|', '&', ';'
    Ignores '&' if it is part of a file descriptor redirection like '2>&1' or '>&'.
    """
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
            # Check 2-char operators first: '&&', '||'
            op2 = cmd[i:i+2]
            if op2 in ('&&', '||'):
                tokens.append((''.join(current).strip(), op2))
                current = []
                i += 2
                continue
            
            # Check file descriptor redirect like 2>&1 or >&2
            if c == '&' and i > 0 and cmd[i-1] == '>':
                current.append(c)
                i += 1
                continue

            # Check 1-char operators: '|', '&', ';'
            if c in ('|', '&', ';'):
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

tc = 'dir /a:h .hermes .artifacts 2>&1 | head -50'
parts = split_compound_command(tc)
for subcmd, op in parts:
    print(f"  [{subcmd}] -> op: '{op}'")
