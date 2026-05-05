import base64
import httpx
import json
from pathlib import Path
from pydantic import BaseModel, Field
from tools.base import BaseTool, ToolResult
from tools.registry import tool
from loguru import logger

@tool(name="screenshot_to_code", description="Convert a UI screenshot or image to HTML/CSS or React code using the vision model.", permissions=["network_read"], risk_score=0.1, blocked_in=[])
class ScreenshotToCodeTool(BaseTool):
    class Input(BaseModel):
        image_path: str = Field(..., description="Path to the image file (PNG, JPG, WEBP)")
        output_format: str = Field(default="html", description="Output format: 'html' or 'react'")
        output_file: str = Field(default="generated_projects/screenshot_output.html", description="Where to save the generated code")
    def execute(self, inp: Input) -> ToolResult:
        try:
            img_path = Path(inp.image_path)
            if not img_path.exists():
                return ToolResult(success=False, output="", error=f"Image not found: {inp.image_path}", exit_code=1, duration_seconds=0.0)
            suffix = img_path.suffix.lower()
            mime_map = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
            mime = mime_map.get(suffix, 'image/png')
            with open(img_path, 'rb') as f:
                img_b64 = base64.b64encode(f.read()).decode('utf-8')
            prompt = (
                f"Convert this UI screenshot to clean {'HTML with Tailwind CSS' if inp.output_format == 'html' else 'React with Tailwind CSS'}. "
                f"Match the layout, colours, and text exactly. Return only the complete code, no explanation."
            )
            response = httpx.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "qwen2.5-coder:7b",
                    "prompt": prompt,
                    "images": [img_b64],
                    "keep_alive": 0,
                    "stream": False
                },
                timeout=120.0
            )
            response.raise_for_status()
            generated_code = response.json().get("response", "")
            if not generated_code:
                return ToolResult(success=False, output="", error="Model returned empty response", exit_code=1, duration_seconds=0.0)
            out_path = Path(inp.output_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(generated_code, encoding='utf-8')
            logger.info(f"screenshot_to_code: generated {len(generated_code)} chars → {inp.output_file}")
            return ToolResult(success=True, output=f"Code generated and saved to {inp.output_file} ({len(generated_code)} chars)", exit_code=0, duration_seconds=0.0)
        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error="Vision model timed out after 120s", exit_code=1, duration_seconds=0.0)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e), exit_code=1, duration_seconds=0.0)
