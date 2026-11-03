import shutil
import subprocess
import tempfile
import re
from pathlib import Path

node_bin = shutil.which("node")
print("Node bin:", node_bin)
if node_bin:
    proc = subprocess.run([node_bin, "--version"], capture_output=True, text=True)
    print("Node version:", proc.stdout.strip())

# Test 1: Valid JS
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write("const x = 1;\nconsole.log(x);")
    p1 = Path(f.name)
res1 = subprocess.run([node_bin, "--check", str(p1)], capture_output=True, text=True)
print("Valid JS exit code:", res1.returncode, "stderr:", res1.stderr)
p1.unlink()

# Test 2: Invalid JS syntax
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write("const x = ;\n")
    p2 = Path(f.name)
res2 = subprocess.run([node_bin, "--check", str(p2)], capture_output=True, text=True)
print("Invalid JS exit code:", res2.returncode)
print("Invalid JS stderr:\n", res2.stderr)
p2.unlink()

# Test 3: .pending extension
with tempfile.NamedTemporaryFile("w", suffix=".pending", delete=False) as f:
    f.write("const x = 1;")
    p3 = Path(f.name)
res3 = subprocess.run([node_bin, "--check", str(p3)], capture_output=True, text=True)
print(".pending exit code:", res3.returncode)
print(".pending stderr:\n", res3.stderr)
p3.unlink()
