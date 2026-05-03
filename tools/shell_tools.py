# tools/shell_tools.py
# Shell execution tools for HERMES.
# ALL shell commands pass through the 15 security gates in tools/security.py first.
# Never call subprocess directly from orchestrator - always use these tools.

import subprocess
import time
import shlex
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from tools.base import BaseTool, ToolResult
from tools.registry import tool
from tools.security import check_all_gates
from loguru import logger


def _command_for_platform(command: str) -> str:
    """Translate minimal POSIX shell commands needed for Windows compatibility."""
    stripped_command = command.strip()
    if Path("C:/Windows").exists() and stripped_command.startswith("sleep "):
        parts = stripped_command.split()
        if len(parts) == 2 and parts[1].isdigit():
            return f'python -c "import time; time.sleep({parts[1]})"'
    return command


@tool(
    name="bash_exec",
    description="Execute a shell command. All commands pass through 15 security gates before execution.",
    permissions=["shell"],
    risk_score=0.7,
    blocked_in=["safe"],
)
class BashExecTool(BaseTool):
    """Execute a shell command after passing all security gates."""

    class Input(BaseModel):
        """Validated input for BashExecTool."""

        command: str = Field(
            ...,
            description="The shell command to execute",
            min_length=1,
            max_length=2000,
        )
        working_dir: str = Field(
            default=".",
            description="Working directory for command execution, relative to project root",
        )
        timeout_seconds: int = Field(
            default=30,
            ge=1,
            le=300,
            description="Maximum seconds to wait for command to complete",
        )

    def execute(self, inp: Input) -> ToolResult:
        """Execute a shell command and return stdout, stderr, exit code, and duration."""
        passed, reason = check_all_gates(inp.command)
        if not passed:
            logger.warning(
                f"bash_exec BLOCKED | cmd={inp.command[:100]!r} | reason={reason}"
            )
            return ToolResult(
                success=False,
                output="",
                error=f"BLOCKED by security gate: {reason}",
                exit_code=126,
            )

        work_dir = Path(inp.working_dir).resolve()
        if not work_dir.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Working directory does not exist: {inp.working_dir}",
                exit_code=1,
            )

        start_time = time.monotonic()
        try:
            command_to_run = _command_for_platform(inp.command)
            result = subprocess.run(
                command_to_run,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(work_dir),
                timeout=inp.timeout_seconds,
            )
            duration = time.monotonic() - start_time
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {inp.timeout_seconds} seconds",
                exit_code=124,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error executing command: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )

        combined_output = result.stdout
        if result.stderr:
            combined_output += (
                f"\n[STDERR]:\n{result.stderr}" if result.stdout else result.stderr
            )

        success = result.returncode == 0
        logger.info(
            f"bash_exec | exit={result.returncode} | duration={duration:.2f}s | "
            f"cmd={inp.command[:60]!r}"
        )
        return ToolResult(
            success=success,
            output=combined_output,
            error=result.stderr if not success else None,
            exit_code=result.returncode,
            duration_seconds=duration,
        )


@tool(
    name="run_python",
    description="Execute a Python file using the current virtual environment's Python interpreter.",
    permissions=["shell"],
    risk_score=0.5,
    blocked_in=["safe"],
)
class RunPythonTool(BaseTool):
    """Execute a Python file with the current interpreter after security checks."""

    class Input(BaseModel):
        """Validated input for RunPythonTool."""

        file_path: str = Field(
            ...,
            description="Path to the Python file to execute, relative to project root",
            min_length=1,
            max_length=500,
        )
        args: list[str] = Field(
            default_factory=list,
            description="Command line arguments to pass to the script",
        )
        working_dir: str = Field(
            default=".",
            description="Working directory, defaults to project root",
        )
        timeout_seconds: int = Field(default=60, ge=1, le=600)

    def execute(self, inp: Input) -> ToolResult:
        """Run a Python file and return stdout, stderr, exit code, and duration."""
        file_path = Path(inp.file_path)
        if not file_path.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Python file not found: {inp.file_path}",
                exit_code=1,
            )
        if not file_path.suffix == ".py":
            return ToolResult(
                success=False,
                output="",
                error=f"File is not a Python file: {inp.file_path}",
                exit_code=1,
            )

        work_dir = Path(inp.working_dir).resolve()
        if not work_dir.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Working directory does not exist: {inp.working_dir}",
                exit_code=1,
            )

        args_str = " ".join(shlex.quote(a) for a in inp.args)
        command = f"{sys.executable} {shlex.quote(str(file_path))} {args_str}".strip()
        passed, reason = check_all_gates(command)
        if not passed:
            logger.warning(
                f"run_python BLOCKED | cmd={command[:100]!r} | reason={reason}"
            )
            return ToolResult(
                success=False,
                output="",
                error=f"BLOCKED by security gate: {reason}",
                exit_code=126,
            )

        start_time = time.monotonic()
        try:
            cmd_list = [sys.executable, str(file_path)] + inp.args
            result = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                cwd=str(work_dir),
                timeout=inp.timeout_seconds,
            )
            duration = time.monotonic() - start_time
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {inp.timeout_seconds} seconds",
                exit_code=124,
                duration_seconds=duration,
            )
        except OSError as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error executing Python file: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )

        combined_output = result.stdout
        if result.stderr:
            combined_output += (
                f"\n[STDERR]:\n{result.stderr}" if result.stdout else result.stderr
            )

        success = result.returncode == 0
        logger.info(
            f"run_python | exit={result.returncode} | duration={duration:.2f}s | "
            f"file={inp.file_path[:60]!r}"
        )
        return ToolResult(
            success=success,
            output=combined_output,
            error=result.stderr if not success else None,
            exit_code=result.returncode,
            duration_seconds=duration,
        )


@tool(
    name="run_tests",
    description="Run a pytest test file and return the results including pass/fail counts.",
    permissions=["shell"],
    risk_score=0.4,
    blocked_in=["safe"],
)
class RunTestsTool(BaseTool):
    """Run pytest for a file or directory after security checks."""

    class Input(BaseModel):
        """Validated input for RunTestsTool."""

        test_path: str = Field(
            ...,
            description="Path to the test file or directory to run",
            min_length=1,
            max_length=500,
        )
        verbose: bool = Field(default=True, description="Run with -v flag for detailed output")
        timeout_seconds: int = Field(default=120, ge=1, le=600)

    def execute(self, inp: Input) -> ToolResult:
        """Run pytest and return full output, exit code, and duration."""
        test_path = Path(inp.test_path)
        if not test_path.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Test path does not exist: {inp.test_path}",
                exit_code=1,
            )

        flags = "-v" if inp.verbose else ""
        command = f"{sys.executable} -m pytest {shlex.quote(inp.test_path)} {flags}".strip()
        passed, reason = check_all_gates(command)
        if not passed:
            logger.warning(
                f"run_tests BLOCKED | cmd={command[:100]!r} | reason={reason}"
            )
            return ToolResult(
                success=False,
                output="",
                error=f"BLOCKED by security gate: {reason}",
                exit_code=126,
            )

        start_time = time.monotonic()
        try:
            cmd_list = [sys.executable, "-m", "pytest", inp.test_path] + (
                ["-v"] if inp.verbose else []
            )
            result = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                timeout=inp.timeout_seconds,
            )
            duration = time.monotonic() - start_time
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {inp.timeout_seconds} seconds",
                exit_code=124,
                duration_seconds=duration,
            )
        except OSError as e:
            duration = time.monotonic() - start_time
            return ToolResult(
                success=False,
                output="",
                error=f"Unexpected error running tests: {str(e)}",
                exit_code=1,
                duration_seconds=duration,
            )

        combined_output = result.stdout
        if result.stderr:
            combined_output += (
                f"\n[STDERR]:\n{result.stderr}" if result.stdout else result.stderr
            )

        summary_line = ""
        for line in result.stdout.split("\n"):
            if "passed" in line or "failed" in line or "error" in line:
                summary_line = line.strip()
                break

        success = result.returncode == 0
        logger.info(
            f"run_tests | exit={result.returncode} | duration={duration:.2f}s | "
            f"summary={summary_line!r}"
        )
        return ToolResult(
            success=success,
            output=combined_output,
            error=result.stderr if not success else None,
            exit_code=result.returncode,
            duration_seconds=duration,
        )
