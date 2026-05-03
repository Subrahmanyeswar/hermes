# tests/test_week1_integration.py
# Plain Python integration script for the HERMES Week 1 pipeline.

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent_classifier import IntentClassifier
from models.ollama_client import OllamaClient
from tools.file_tools import ListDirectoryTool, ReadFileTool, WriteFileTool

__test__ = False


async def test_vram_baseline() -> None:
    """Verify Ollama is available before running live integration checks."""
    client = OllamaClient()
    assert await client.is_running() is True
    print("Ollama is running.")


async def test_model_responds_and_unloads() -> None:
    """Verify qwen2.5-coder:7b responds and the call uses keep_alive=0."""
    client = OllamaClient()
    response = await client.generate(
        "qwen2.5-coder:7b",
        "Write hello world in Python",
        keep_alive=0,
    )

    assert isinstance(response, str)
    assert response.strip()
    assert "print" in response
    print(f"Response length: {len(response)}")
    print("Model responded and VRAM released (keep_alive=0).")


async def test_skill_injection_into_prompt() -> None:
    """Verify classifier selects and loads the Flask skill content."""
    classifier = IntentClassifier("skills/")
    skill_ids = classifier.classify("build a flask rest api with login endpoint")
    assert skill_ids == ["flask-rest-api"]

    skill_content = classifier.load_skill_content(skill_ids[0])
    assert isinstance(skill_content, str)
    assert skill_content.strip()
    assert "Flask" in skill_content
    print("Skill correctly identified and loaded.")


async def test_file_tool_write_and_read() -> None:
    """Verify write, read, and list file tools work together."""
    path = "generated_projects/test_integration_output.py"
    content = 'print("HERMES Week 1 integration test passed")\n'

    write_result = WriteFileTool().execute(
        WriteFileTool.Input(path=path, content=content)
    )
    assert write_result.success is True

    read_result = ReadFileTool().execute(ReadFileTool.Input(path=path))
    assert read_result.success is True
    assert "HERMES Week 1 integration test passed" in read_result.output

    list_result = ListDirectoryTool().execute(
        ListDirectoryTool.Input(path="generated_projects/")
    )
    assert list_result.success is True
    assert "test_integration_output.py" in list_result.output
    print("File tools: write, read, list all working.")


async def test_full_pipeline_prompt_to_tool_call() -> None:
    """Verify Tier 1 can produce a valid JSON tool call for a file request."""
    client = OllamaClient()
    system_prompt = """
You are HERMES, an agentic coding assistant.
You must respond with ONLY valid JSON. No explanation, no markdown, no text before or after the JSON.

Available tools:
- read_file: Read the contents of a file
- write_file: Write content to a file
- list_directory: List files in a directory

Respond in this exact JSON format:
{
  "reasoning": "brief explanation of what you will do",
  "tool": "tool_name",
  "parameters": { ... tool-specific parameters ... },
  "explanation": "one sentence for the user"
}

For file creation requests, always choose write_file.
The write_file parameters must include "path", "content", and "mode".
Use mode "overwrite" unless the user asks to append.

Example valid response:
{
  "reasoning": "The user wants a new Python file that prints hello world.",
  "tool": "write_file",
  "parameters": {
    "path": "hello.py",
    "content": "print(\\"hello world\\")\\n",
    "mode": "overwrite"
  },
  "explanation": "I will create hello.py with a hello world print statement."
}
""".strip()
    user_prompt = "Create a Python file called hello.py that prints hello world"

    response = await client.generate(
        "qwen2.5-coder:7b",
        user_prompt,
        system=system_prompt,
        keep_alive=0,
    )
    parsed: dict[str, Any] = json.loads(response)

    assert "reasoning" in parsed
    assert "tool" in parsed
    assert "parameters" in parsed
    assert "explanation" in parsed
    assert parsed["tool"] == "write_file"
    assert "path" in parsed["parameters"]
    print(json.dumps(parsed, indent=2))
    print("Tier 1 produced valid JSON tool call.")


async def main() -> None:
    """Run all Week 1 integration tests and print a summary."""
    tests: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("test_vram_baseline", test_vram_baseline),
        ("test_model_responds_and_unloads", test_model_responds_and_unloads),
        ("test_skill_injection_into_prompt", test_skill_injection_into_prompt),
        ("test_file_tool_write_and_read", test_file_tool_write_and_read),
        ("test_full_pipeline_prompt_to_tool_call", test_full_pipeline_prompt_to_tool_call),
    ]
    failures: list[str] = []

    for test_name, test_function in tests:
        start_time = time.perf_counter()
        try:
            await test_function()
        except AssertionError as exc:
            failures.append(test_name)
            print(f"{test_name} failed: {exc}")
        except Exception as exc:
            failures.append(test_name)
            print(f"{test_name} failed with {type(exc).__name__}: {exc}")
        else:
            duration_seconds = time.perf_counter() - start_time
            print(f"{test_name} passed in {duration_seconds:.2f}s")

    if not failures:
        print("WEEK 1 COMPLETE: All integration tests passed.")
    else:
        print(f"WEEK 1 INCOMPLETE: {len(failures)} tests failed.")
        print(f"Failures: {failures}")


if __name__ == "__main__":
    asyncio.run(main())
