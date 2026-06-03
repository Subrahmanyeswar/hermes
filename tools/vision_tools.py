# tools/vision_tools.py
# HERMES vision tools — screenshot-to-code generation.
# ScreenshotToCodeTool: converts a UI screenshot to HTML+CSS or React code
#                       using Qwen2.5-Coder 7B's vision (multimodal) endpoint.
#
# Qwen2.5-Coder 7B supports vision via Ollama's multimodal API.
# Images are sent as base64-encoded strings in the 'images' field.
# The model analyses the screenshot and generates matching frontend code.
#
# Note: vision inference is slower than text — expect 20-60 seconds.
import base64
import json
import re
import time
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
from tools.base import BaseTool, ToolResult
from tools.registry import tool
from loguru import logger


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

MIME_TYPE_MAP = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif":  "image/gif",
}

# ── System prompts by output format ──────────────────────────────────

HTML_SYSTEM_PROMPT = """You are an expert frontend developer. 
Convert the provided UI screenshot into clean, complete HTML with inline Tailwind CSS.

Rules:
1. Reproduce the layout, spacing, and colour scheme as accurately as possible
2. Use Tailwind CSS utility classes for all styling — no custom CSS
3. Use semantic HTML: header, nav, main, section, article, footer, button, input
4. Match the exact text content visible in the screenshot
5. For colours: use Tailwind's colour palette (e.g. bg-blue-600, text-gray-900)
6. Make it responsive: add sm: md: lg: breakpoint classes where appropriate
7. Output ONLY the complete HTML file — no explanation, no markdown fences
8. Start with <!DOCTYPE html> and end with </html>
"""

REACT_SYSTEM_PROMPT = """You are an expert React developer.
Convert the provided UI screenshot into a clean, complete React functional component with Tailwind CSS.

Rules:
1. Reproduce the layout, spacing, and colour scheme as accurately as possible
2. Use Tailwind CSS utility classes for all styling
3. Create a single functional component named 'GeneratedComponent'
4. Use appropriate semantic JSX elements
5. Match the exact text content visible in the screenshot
6. Add useState for any visible interactive elements (toggles, inputs, tabs)
7. Export the component as default
8. Output ONLY the complete React component — no explanation, no markdown fences
9. Start with import statements and end with export default GeneratedComponent
"""


@tool(
    name="screenshot_to_code",
    description=(
        "Convert a UI screenshot or image to HTML+Tailwind or React+Tailwind code. "
        "Uses the Qwen2.5-Coder vision model. "
        "Supported formats: PNG, JPG, JPEG, WEBP. "
        "Output is saved to a file and the path is returned."
    ),
    permissions=["network_read"],
    risk_score=0.1,
    blocked_in=[],
)
class ScreenshotToCodeTool(BaseTool):

    class Input(BaseModel):
        image_path: str = Field(
            ...,
            description="Path to the screenshot image file (PNG, JPG, WEBP)",
            min_length=1,
            max_length=500,
        )
        output_format: Literal["html", "react"] = Field(
            default="html",
            description="Output code format: 'html' for HTML+Tailwind, 'react' for React+Tailwind",
        )
        output_file: str = Field(
            default="",
            description=(
                "Where to save the generated code. "
                "Defaults to generated_projects/screenshot_output.html or .jsx"
            ),
        )
        ollama_url: str = Field(
            default="http://localhost:11434",
            description="Ollama server URL",
        )

    def execute(self, inp: Input) -> ToolResult:
        start = time.monotonic()

        # ── Validate image file ───────────────────────────────────────
        img_path = Path(inp.image_path)
        if not img_path.exists():
            return ToolResult(
                success=False,
                error=f"Image file not found: {inp.image_path}",
                exit_code=1,
            )

        suffix = img_path.suffix.lower()
        if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
            return ToolResult(
                success=False,
                error=(
                    f"Unsupported image format: {suffix}. "
                    f"Supported: {', '.join(SUPPORTED_IMAGE_EXTENSIONS)}"
                ),
                exit_code=1,
            )

        # ── Determine output path ─────────────────────────────────────
        if inp.output_file:
            out_path = Path(inp.output_file)
        else:
            ext = ".jsx" if inp.output_format == "react" else ".html"
            out_name = f"screenshot_{img_path.stem}_output{ext}"
            out_path = Path("generated_projects") / out_name

        out_path.parent.mkdir(parents=True, exist_ok=True)

        # ── Encode image as base64 ────────────────────────────────────
        try:
            with open(img_path, "rb") as f:
                img_bytes = f.read()
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
            img_size_kb = len(img_bytes) / 1024
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to read image file: {e}",
                exit_code=1,
            )

        logger.info(
            f"screenshot_to_code: processing {img_path.name} "
            f"({img_size_kb:.1f}KB) → {inp.output_format}"
        )

        # ── Build prompt ──────────────────────────────────────────────
        system_prompt = (
            HTML_SYSTEM_PROMPT
            if inp.output_format == "html"
            else REACT_SYSTEM_PROMPT
        )

        user_prompt = (
            f"Convert this UI screenshot to "
            f"{'HTML with Tailwind CSS' if inp.output_format == 'html' else 'React with Tailwind CSS'}. "
            f"Match the layout, colours, and text exactly. "
            f"Output only the complete code, nothing else."
        )

        # ── Call Ollama multimodal endpoint ───────────────────────────
        try:
            import httpx

            request_body = {
                "model": "qwen2.5-coder:7b",
                "prompt": user_prompt,
                "system": system_prompt,
                "images": [img_b64],
                "keep_alive": 0,
                "stream": False,
                "options": {
                    "num_ctx": 8192,  # More context for code generation
                    "temperature": 0.1,  # Low temperature for deterministic code
                },
            }

            with httpx.Client(timeout=120.0) as client:
                response = client.post(
                    f"{inp.ollama_url}/api/generate",
                    json=request_body,
                )
                response.raise_for_status()
                data = response.json()

        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                error=(
                    "Vision model timed out after 120 seconds. "
                    "Screenshot-to-code inference is slow — this is normal for large images. "
                    "Try a smaller screenshot or wait and retry."
                ),
                exit_code=124,
                duration_seconds=time.monotonic() - start,
            )
        except httpx.ConnectError:
            return ToolResult(
                success=False,
                error=(
                    "Cannot connect to Ollama. "
                    "Make sure Ollama is running: ollama serve"
                ),
                exit_code=1,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Ollama API error: {type(e).__name__}: {str(e)[:200]}",
                exit_code=1,
            )

        # ── Extract generated code ────────────────────────────────────
        generated_code = data.get("response", "").strip()

        if not generated_code:
            return ToolResult(
                success=False,
                error="Model returned empty response. Try again with a clearer screenshot.",
                exit_code=1,
            )

        # Clean up markdown fences if model added them
        generated_code = self._clean_code_output(generated_code, inp.output_format)

        if not generated_code:
            return ToolResult(
                success=False,
                error="Could not extract valid code from model response.",
                exit_code=1,
            )

        # ── Write output file ─────────────────────────────────────────
        try:
            out_path.write_text(generated_code, encoding="utf-8")
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to write output file {out_path}: {e}",
                exit_code=1,
            )

        duration = time.monotonic() - start
        code_lines = generated_code.count("\n") + 1

        logger.info(
            f"screenshot_to_code: generated {code_lines} lines of {inp.output_format} "
            f"→ {out_path} | {duration:.1f}s"
        )

        return ToolResult(
            success=True,
            output=(
                f"Code generated successfully.\n"
                f"Format:  {inp.output_format.upper()} + Tailwind CSS\n"
                f"Output:  {out_path}\n"
                f"Lines:   {code_lines}\n"
                f"Time:    {duration:.1f}s\n"
                f"Preview: {generated_code[:200]}..."
            ),
            exit_code=0,
            duration_seconds=duration,
        )

    def _clean_code_output(self, raw: str, output_format: str) -> str:
        """
        Strip markdown fences and return only the code.
        Handles: ```html, ```jsx, ```react, ``` (generic), no fence.
        """
        # Try to extract from fenced code block
        patterns = [
            r"```(?:html|jsx|react|javascript|js|tsx|typescript)\s*\n(.*?)\n?```",
            r"```\s*\n(.*?)\n?```",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()

        # No fence — check if it looks like code
        stripped = raw.strip()
        if output_format == "html" and (
            stripped.startswith("<!DOCTYPE") or stripped.startswith("<html") or stripped.startswith("<div")
        ):
            return stripped
        if output_format == "react" and (
            "import " in stripped or "export default" in stripped or "function " in stripped
        ):
            return stripped

        # Return as-is if we can't determine
        return stripped
