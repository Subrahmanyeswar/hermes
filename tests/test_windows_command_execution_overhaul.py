# tests/test_windows_command_execution_overhaul.py
# Verification and regression suite for Windows command execution and translation overhaul

import sys
import os
import subprocess
from pathlib import Path
import pytest

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.shell_tools import _command_for_platform, _split_compound_command, BashExecTool
from core.runtime_identity import get_canonical_python_executable


def test_split_compound_command_operators():
    cmd = 'echo "hello && world" && pwd; ls -la | head -10'
    pairs = _split_compound_command(cmd)
    assert len(pairs) == 4
    assert pairs[0] == ('echo "hello && world"', '&&')
    assert pairs[1] == ('pwd', ';')
    assert pairs[2] == ('ls -la', '|')
    assert pairs[3] == ('head -10', '')


def test_split_compound_command_redirection_protection():
    cmd = 'dir /a:h .hermes .artifacts 2>&1 | head -50'
    pairs = _split_compound_command(cmd)
    assert len(pairs) == 2
    assert pairs[0] == ('dir /a:h .hermes .artifacts 2>&1', '|')
    assert pairs[1] == ('head -50', '')


def test_command_for_platform_paths_with_spaces(tmp_path):
    ws_with_space = tmp_path / "space workspace test"
    ws_with_space.mkdir(parents=True)
    (ws_with_space / "sample.txt").write_text("hermes test payload", encoding="utf-8")

    cmd = f'ls -la "{ws_with_space}"'
    translated = _command_for_platform(cmd)

    py = get_canonical_python_executable()
    assert py in translated
    # Space workspace must be preserved in quotes
    assert str(ws_with_space) in translated

    # Run the translated command
    res = subprocess.run(translated, shell=True, capture_output=True, text=True)
    assert res.returncode == 0
    assert "sample.txt" in res.stdout


def test_command_for_platform_dev_null_suppression():
    cmd = 'node --version 2>/dev/null && echo SUCCESS'
    translated = _command_for_platform(cmd)
    assert "/dev/null" not in translated
    assert "2>NUL" in translated

    res = subprocess.run(translated, shell=True, capture_output=True, text=True)
    assert res.returncode == 0
    assert "SUCCESS" in res.stdout


def test_command_for_platform_compound_chain_with_pwd_and_ls(tmp_path):
    sub = tmp_path / "deep test"
    sub.mkdir()
    (sub / "alpha.js").write_text("console.log('hi')", encoding="utf-8")

    cmd = f'pwd && ls "{sub}" && echo "---DONE---"'
    translated = _command_for_platform(cmd)

    res = subprocess.run(translated, shell=True, capture_output=True, text=True, cwd=str(tmp_path))
    assert res.returncode == 0
    assert "alpha.js" in res.stdout
    assert "---DONE---" in res.stdout


def test_command_for_platform_head_pipeline():
    # Pipe output to head -3
    cmd = f'python -c "for i in range(20): print(f\'line_{{i}}\')" | head -3'
    translated = _command_for_platform(cmd)

    res = subprocess.run(translated, shell=True, capture_output=True, text=True)
    assert res.returncode == 0
    lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    assert lines == ["line_0", "line_1", "line_2"]


def test_bash_exec_tool_execution(tmp_path):
    ws = tmp_path / "exec test"
    ws.mkdir()
    (ws / "file.txt").write_text("data line", encoding="utf-8")

    tool = BashExecTool()
    inp = BashExecTool.Input(
        command=f'cat "{ws / "file.txt"}"',
        working_dir=str(ws)
    )
    result = tool.execute(inp)
    assert result.success is True
    assert result.exit_code == 0
    assert "data line" in result.output
