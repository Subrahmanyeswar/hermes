import subprocess
import sys
from pathlib import Path

py = sys.executable
ws = r"C:\Users\SUBBU\Downloads\rocket4 hermes test"

# Test 1: pwd and dev/null
cmd1 = f'cd && dir /b && echo ---NODE--- && node --version 2>NUL && echo ---NPM--- && npm --version 2>NUL && echo ---PYTHON--- && "{py}" --version 2>NUL'
r1 = subprocess.run(cmd1, shell=True, capture_output=True, text=True, cwd=ws)
print('Cmd 1 exit:', r1.returncode)
print('Cmd 1 stdout:', r1.stdout.strip())

# Test 2: path with spaces
cmd2 = f'dir /a "{ws}" && echo ---HERMES--- && dir /a "{ws}\\.hermes" 2>NUL'
r2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
print('\nCmd 2 exit:', r2.returncode)
print('Cmd 2 stdout:', r2.stdout[:150])

# Test 4: head translation
py_head = f'"{py}" -c "import sys; [sys.stdout.write(sys.stdin.readline()) for _ in range(5)]"'
cmd4 = f'dir /a "{ws}" | {py_head}'
r4 = subprocess.run(cmd4, shell=True, capture_output=True, text=True)
print('\nCmd 4 exit:', r4.returncode)
print('Cmd 4 stdout:\n', r4.stdout)
