import sys
import os
import shlex
from pathlib import Path

py = sys.executable

def split_compound_command(cmd: str):
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
            op2 = cmd[i:i+2]
            if op2 in ('&&', '||'):
                tokens.append((''.join(current).strip(), op2))
                current = []
                i += 2
                continue
            if c == '&' and i > 0 and cmd[i-1] == '>':
                current.append(c)
                i += 1
                continue
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

def translate_single_command(cmd: str, py: str) -> str:
    stripped = cmd.strip()
    if not stripped:
        return ""

    # Replace /dev/null with NUL
    stripped = stripped.replace("/dev/null", "NUL")

    # Normalize python invocations
    if stripped.startswith("python "):
        stripped = f'"{py}" ' + stripped[7:]
    elif stripped == "python":
        stripped = f'"{py}"'
    elif stripped.startswith("python3 "):
        stripped = f'"{py}" ' + stripped[8:]
    elif stripped == "python3":
        stripped = f'"{py}"'
    elif stripped.startswith("pytest "):
        stripped = f'"{py}" -m pytest ' + stripped[7:]
    elif stripped == "pytest":
        stripped = f'"{py}" -m pytest'

    if sys.platform != "win32" and not Path("C:/Windows").exists():
        return stripped

    # POSIX on Windows builtins
    if stripped == "pwd":
        return f'"{py}" -c "import os; print(os.getcwd())"'

    try:
        parts = shlex.split(stripped, posix=False)
    except Exception:
        parts = stripped.split()

    if not parts:
        return stripped

    lead = parts[0].strip('"\'')

    if lead == "pwd":
        return f'"{py}" -c "import os; print(os.getcwd())"'

    if lead == "ls":
        non_flags = [p.strip('"\'') for p in parts[1:] if not p.strip('"\'').startswith("-")]
        target = non_flags[0] if non_flags else "."
        target_esc = target.replace('"', '\\"')
        py_code = "import os, sys; p = sys.argv[1] if len(sys.argv) > 1 else '.'; (print('\\n'.join(sorted(os.listdir(p)))) if os.path.isdir(p) else (print(p) if os.path.exists(p) else (print('ls: cannot access ' + p + ': No such file or directory', file=sys.stderr), sys.exit(1))))"
        return f'"{py}" -c "{py_code}" "{target_esc}"'

    if lead == "cat" and len(parts) > 1:
        target = parts[1].strip('"\'')
        target_esc = target.replace('"', '\\"')
        py_code = "import os, sys; p=sys.argv[1]; (sys.stdout.write(open(p, 'r', encoding='utf-8', errors='replace').read()) if os.path.exists(p) else (print('cat: ' + p + ': No such file or directory', file=sys.stderr), sys.exit(1)))"
        return f'"{py}" -c "{py_code}" "{target_esc}"'

    if lead == "head":
        # e.g. head -50 or head -n 50
        n_lines = 10
        if len(parts) > 1:
            arg = parts[1].strip('"\'')
            if arg.startswith("-") and arg[1:].isdigit():
                n_lines = int(arg[1:])
            elif arg == "-n" and len(parts) > 2 and parts[2].strip('"\'').isdigit():
                n_lines = int(parts[2].strip('"\''))
        py_code = f"import sys; [sys.stdout.write(l) for _, l in zip(range({n_lines}), sys.stdin)]"
        return f'"{py}" -c "{py_code}"'

    if lead == "which" and len(parts) > 1:
        target = parts[1].strip('"\'')
        return f"where {target}"

    if lead == "sleep" and len(parts) > 1 and parts[1].isdigit():
        return f'"{py}" -c "import time; time.sleep({parts[1]})"'

    if lead == "mkdir" and "-p" in [p.strip('"\'') for p in parts[1:]]:
        targets = [p.strip('"\'') for p in parts[1:] if p.strip('"\'') != "-p"]
        target = targets[0] if targets else "."
        target_esc = target.replace('"', '\\"')
        return f'"{py}" -c "import os, sys; os.makedirs(sys.argv[1], exist_ok=True)" "{target_esc}"'

    if lead == "touch" and len(parts) > 1:
        target = parts[1].strip('"\'')
        target_esc = target.replace('"', '\\"')
        return f'"{py}" -c "import pathlib, sys; pathlib.Path(sys.argv[1]).touch(exist_ok=True)" "{target_esc}"'

    return stripped

def translate_command(command: str, py: str) -> str:
    pairs = split_compound_command(command)
    translated_parts = []
    for subcmd, op in pairs:
        t_sub = translate_single_command(subcmd, py)
        # On Windows cmd.exe, ';' maps to '&'
        norm_op = '&' if op == ';' else op
        translated_parts.append((t_sub, norm_op))

    # Recombine
    result = ""
    for sub, op in translated_parts:
        if result:
            result += " "
        result += sub
        if op:
            result += f" {op}"
    return result

# Test the exact failed command from the incident
cmd = 'pwd && ls -la && echo "---NODE---" && node --version 2>/dev/null && echo "---NPM---" && npm --version 2>/dev/null && echo "---PYTHON---" && python --version 2>/dev/null && echo "---DIR---" && ls -la "C:\\Users\\SUBBU\\Downloads\\rocket4 hermes test"'
translated = translate_command(cmd, py)
print("TRANSLATED:")
print(translated)
print("\nRUNNING VIA SUBPROCESS:")
import subprocess
res = subprocess.run(translated, shell=True, capture_output=True, text=True)
print("EXIT CODE:", res.returncode)
print("STDOUT:\n", res.stdout)
print("STDERR:\n", res.stderr)
