import shutil
import subprocess
import sys
from pathlib import Path
from pydantic import BaseModel, Field
from tools.base import BaseTool, ToolResult
from tools.registry import tool
from loguru import logger

@tool(name="export_zip", description="Export a project folder as a ZIP file for download or sharing.", permissions=["filesystem_read"], risk_score=0.1, blocked_in=[])
class ExportZipTool(BaseTool):
    class Input(BaseModel):
        project_path: str = Field(..., description="Path to the project folder to export")
        output_name: str = Field(default="", description="Name for the ZIP file without extension. Defaults to folder name.")
    def execute(self, inp: Input) -> ToolResult:
        try:
            src = Path(inp.project_path)
            if not src.exists():
                return ToolResult(success=False, output="", error=f"Project path not found: {inp.project_path}", exit_code=1, duration_seconds=0.0)
            name = inp.output_name or src.name
            output_dir = Path("generated_projects")
            output_dir.mkdir(parents=True, exist_ok=True)
            zip_path = output_dir / name
            result_path = shutil.make_archive(str(zip_path), 'zip', str(src.parent), src.name)
            logger.info(f"export_zip: created {result_path}")
            return ToolResult(success=True, output=f"ZIP exported to: {result_path}", exit_code=0, duration_seconds=0.0)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=0.0)

@tool(name="open_in_vscode", description="Open a file or folder in VS Code editor.", permissions=["shell"], risk_score=0.1, blocked_in=[])
class OpenInVSCodeTool(BaseTool):
    class Input(BaseModel):
        path: str = Field(default=".", description="Path to open in VS Code")
    def execute(self, inp: Input) -> ToolResult:
        try:
            subprocess.Popen(["code", inp.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ToolResult(success=True, output=f"Opened in VS Code: {inp.path}", exit_code=0, duration_seconds=0.0)
        except FileNotFoundError:
            return ToolResult(success=False, output="", error="VS Code 'code' command not found. Install VS Code and add it to PATH.", exit_code=1, duration_seconds=0.0)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=0.0)
