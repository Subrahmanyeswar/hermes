import shlex

cmd = 'ls -la "C:\\Users\\SUBBU\\Downloads\\rocket4 hermes test"'
print("posix=True:", shlex.split(cmd, posix=True))
print("posix=False:", shlex.split(cmd, posix=False))
