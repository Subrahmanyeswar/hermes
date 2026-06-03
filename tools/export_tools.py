# tools/export_tools.py
# HERMES export tools — demo-grade project export capabilities.
# ExportZipTool:    packages a project folder as a ZIP archive
# OpenInVSCodeTool: opens a file or folder in VS Code via `code` CLI
#
# These tools are intentionally simple — they call shutil and subprocess.
# They are not security-sensitive because they only operate on paths the
# agent has already created (in generated_projects/).

import shutil
import subprocess
import sys
import time
from pathlib import Path
from pydantic import BaseModel, Field
from tools.base import BaseTool, ToolResult
from tools.registry import tool
from loguru import logger


@tool(
    name="export_zip",
    description=(
        "Export a project folder as a ZIP archive. "
        "The ZIP is saved to generated_projects/ and the full path is returned."
    ),
    permissions=["filesystem_read"],
    risk_score=0.1,
    blocked_in=[],
)
class ExportZipTool(BaseTool):

    class Input(BaseModel):
        project_path: str = Field(
            ...,
            description="Path to the project folder to export",
            min_length=1,
            max_length=500,
        )
        output_name: str = Field(
            default="",
            description=(
                "Name for the ZIP file without extension. "
                "Defaults to the folder name."
            ),
        )

    def execute(self, inp: Input) -> ToolResult:
        start = time.monotonic()
        try:
            src = Path(inp.project_path)
            if not src.exists():
                return ToolResult(
                    success=False,
                    error=f"Project path not found: {inp.project_path}",
                    exit_code=1,
                )
            if not src.is_dir():
                return ToolResult(
                    success=False,
                    error=f"Path is not a directory: {inp.project_path}",
                    exit_code=1,
                )

            name = inp.output_name.strip() or src.name
            # Sanitise the name — no path separators or spaces
            name = name.replace("/", "_").replace("\\", "_").replace(" ", "_")

            output_dir = Path("generated_projects")
            output_dir.mkdir(parents=True, exist_ok=True)

            zip_base = str(output_dir / name)

            # shutil.make_archive returns the full path including extension
            result_path = shutil.make_archive(
                base_name=zip_base,
                format="zip",
                root_dir=str(src.parent),
                base_dir=src.name,
            )

            duration = time.monotonic() - start
            size_mb = Path(result_path).stat().st_size / (1024 * 1024)

            logger.info(
                f"export_zip: created {result_path} | "
                f"{size_mb:.2f}MB | {duration:.2f}s"
            )
            return ToolResult(
                success=True,
                output=(
                    f"ZIP exported successfully.\n"
                    f"Path:  {result_path}\n"
                    f"Size:  {size_mb:.2f} MB\n"
                    f"From:  {inp.project_path}"
                ),
                exit_code=0,
                duration_seconds=duration,
            )

        except PermissionError as e:
            return ToolResult(
                success=False,
                error=f"Permission denied creating ZIP: {e}",
                exit_code=1,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"ZIP export failed: {type(e).__name__}: {str(e)[:200]}",
                exit_code=1,
            )


@tool(
    name="open_in_vscode",
    description=(
        "Open a file or folder in VS Code. "
        "Requires VS Code to be installed with the 'code' CLI command available."
    ),
    permissions=["shell"],
    risk_score=0.1,
    blocked_in=[],
)
class OpenInVSCodeTool(BaseTool):

    class Input(BaseModel):
        path: str = Field(
            default=".",
            description="File or folder path to open in VS Code. Defaults to current directory.",
            max_length=500,
        )
        new_window: bool = Field(
            default=False,
            description="Open in a new VS Code window instead of reusing existing.",
        )

    def execute(self, inp: Input) -> ToolResult:
        start = time.monotonic()
        try:
            target = Path(inp.path)
            if not target.exists():
                return ToolResult(
                    success=False,
                    error=f"Path does not exist: {inp.path}",
                    exit_code=1,
                )

            cmd = ["code"]
            if inp.new_window:
                cmd.append("--new-window")
            cmd.append(str(target.resolve()))

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                stdin=subprocess.DEVNULL,
            )

            # Give it 1 second to fail fast (e.g. code not found)
            try:
                _, stderr = proc.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                # Good — VS Code launched and is running
                stderr = ""

            duration = time.monotonic() - start

            if proc.returncode is not None and proc.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"VS Code returned exit code {proc.returncode}: {stderr[:200]}",
                    exit_code=proc.returncode,
                    duration_seconds=duration,
                )

            logger.info(f"open_in_vscode: opened {target.resolve()} | {duration:.2f}s")
            return ToolResult(
                success=True,
                output=f"Opened in VS Code: {target.resolve()}",
                exit_code=0,
                duration_seconds=duration,
            )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=(
                    "VS Code 'code' command not found. "
                    "Install VS Code and add it to your PATH: "
                    "https://code.visualstudio.com/docs/setup/setup-overview"
                ),
                exit_code=127,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to open VS Code: {type(e).__name__}: {str(e)[:200]}",
                exit_code=1,
            )
