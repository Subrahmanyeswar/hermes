import subprocess
import time
import urllib.request
import json
import sys

# Test running TaskForge on port 8001 using canonical Python
python_exe = r"C:\Users\SUBBU\Downloads\hermes\venv\Scripts\python.exe"
proc = subprocess.Popen(
    [python_exe, "-m", "uvicorn", "main:app", "--port", "8001", "--host", "127.0.0.1"],
    cwd=r"C:\Users\SUBBU\Downloads\testing 2",
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

time.sleep(2)
try:
    with urllib.request.urlopen("http://127.0.0.1:8001/api/tasks") as resp:
        print("HTTP Status:", resp.status)
        data = json.loads(resp.read().decode("utf-8"))
        print("Tasks count:", len(data))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except Exception:
        proc.kill()
    print("Process cleanly terminated")
