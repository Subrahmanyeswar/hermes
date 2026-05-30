# tools/prompt_tester.py
# System prompt reliability tester for HERMES.
# Runs 50 diverse user prompts through Tier 1 (Qwen2.5-Coder 7B) and measures
# JSON parse success rate, failure modes, and tool selection accuracy.
# Used in Week 10 to validate the system prompt before adding any new features.
# Run: python tools/prompt_tester.py
# Target: >= 90% JSON parse success rate across all 50 prompts.

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.prompt_builder import PromptContext, build_system_prompt
from tools.registry import tool_schema_for_prompt, list_tools
from core.intent_classifier import IntentClassifier

@dataclass
class PromptTestResult:
    """Result of testing one prompt through Tier 1."""
    prompt_id: str
    user_prompt: str
    category: str                        # e.g. "file_ops", "git", "web", "shell"
    expected_tool: Optional[str]         # What tool we expect Tier 1 to pick
    
    # Results filled in after generation
    raw_response: str = ""
    parsed_successfully: bool = False
    actual_tool: Optional[str] = None
    tool_correct: bool = False           # Did Tier 1 pick the expected tool?
    failure_reason: Optional[str] = None # If parse failed, why?
    latency_seconds: float = 0.0
    response_length: int = 0

TEST_PROMPTS: list[dict] = [
    # ── Category: file_ops (10 prompts) ──────────────────────────────
    {"id": "F01", "category": "file_ops", "expected": "read_file",
     "prompt": "Read the contents of the file config/settings.yaml and show me what is inside"},
    {"id": "F02", "category": "file_ops", "expected": "write_file",
     "prompt": "Create a new Python file at generated_projects/hello.py that prints hello world"},
    {"id": "F03", "category": "file_ops", "expected": "list_directory",
     "prompt": "Show me all the files and folders in the current directory"},
    {"id": "F04", "category": "file_ops", "expected": "write_file",
     "prompt": "Write a requirements.txt file with flask==3.0.0 and pydantic==2.7.0 on separate lines"},
    {"id": "F05", "category": "file_ops", "expected": "read_file",
     "prompt": "Open and display the README.md file"},
    {"id": "F06", "category": "file_ops", "expected": "create_folder",
     "prompt": "Create a new folder called myproject with subfolders src and tests"},
    {"id": "F07", "category": "file_ops", "expected": "write_file",
     "prompt": "Make a Python configuration file at config.py that defines a DATABASE_URL variable"},
    {"id": "F08", "category": "file_ops", "expected": "list_directory",
     "prompt": "What files are currently in the tests directory"},
    {"id": "F09", "category": "file_ops", "expected": "append_file",
     "prompt": "Add a new line to the existing requirements.txt file with requests==2.31.0"},
    {"id": "F10", "category": "file_ops", "expected": "read_file",
     "prompt": "Show me the contents of main.py"},

    # ── Category: shell (10 prompts) ─────────────────────────────────
    {"id": "S01", "category": "shell", "expected": "bash_exec",
     "prompt": "Run python --version to check what Python version is installed"},
    {"id": "S02", "category": "shell", "expected": "run_python",
     "prompt": "Execute the Python script at generated_projects/hello.py"},
    {"id": "S03", "category": "shell", "expected": "run_tests",
     "prompt": "Run the pytest test suite at tests/test_tools.py and show me the results"},
    {"id": "S04", "category": "shell", "expected": "bash_exec",
     "prompt": "List all Python files in the current directory using the find command"},
    {"id": "S05", "category": "shell", "expected": "bash_exec",
     "prompt": "Check if the port 5000 is in use on this machine"},
    {"id": "S06", "category": "shell", "expected": "run_python",
     "prompt": "Run the script tools/prompt_tester.py"},
    {"id": "S07", "category": "shell", "expected": "bash_exec",
     "prompt": "Show me the current working directory using pwd"},
    {"id": "S08", "category": "shell", "expected": "bash_exec",
     "prompt": "Count how many lines are in the file core/orchestrator.py"},
    {"id": "S09", "category": "shell", "expected": "run_tests",
     "prompt": "Execute all tests in the tests folder and report which ones pass and fail"},
    {"id": "S10", "category": "shell", "expected": "bash_exec",
     "prompt": "Show me the git log for the last 5 commits"},

    # ── Category: git (5 prompts) ─────────────────────────────────────
    {"id": "G01", "category": "git", "expected": "git_init",
     "prompt": "Initialise a new git repository in the generated_projects/myapp folder"},
    {"id": "G02", "category": "git", "expected": "git_add_commit",
     "prompt": "Commit all the current changes with the message feat: add Flask API routes"},
    {"id": "G03", "category": "git", "expected": "git_add_commit",
     "prompt": "Stage all files and create a commit saying initial project setup"},
    {"id": "G04", "category": "git", "expected": "git_push",
     "prompt": "Push the committed changes to the GitHub remote repository"},
    {"id": "G05", "category": "git", "expected": "git_init",
     "prompt": "Set up a new git repo for my project and make the initial commit"},

    # ── Category: web (5 prompts) ─────────────────────────────────────
    {"id": "W01", "category": "web", "expected": "web_search",
     "prompt": "Search the web for Flask REST API best practices 2024"},
    {"id": "W02", "category": "web", "expected": "web_fetch",
     "prompt": "Fetch the content of the URL https://httpbin.org/get"},
    {"id": "W03", "category": "web", "expected": "web_search",
     "prompt": "Look up the latest documentation for SQLAlchemy 2.0"},
    {"id": "W04", "category": "web", "expected": "web_search",
     "prompt": "Find information about pytest fixtures online"},
    {"id": "W05", "category": "web", "expected": "web_fetch",
     "prompt": "Get the content from https://pypi.org/pypi/flask/json"},

    # ── Category: memory (5 prompts) ─────────────────────────────────
    {"id": "M01", "category": "memory", "expected": "save_memory",
     "prompt": "Remember that this project uses PostgreSQL not SQLite for the application database"},
    {"id": "M02", "category": "memory", "expected": "save_memory",
     "prompt": "Note that the main entry point is run.py and the app runs on port 8080"},
    {"id": "M03", "category": "memory", "expected": "read_memory",
     "prompt": "Read the database schema topic from project memory"},
    {"id": "M04", "category": "memory", "expected": "save_memory",
     "prompt": "Keep in mind that authentication uses JWT tokens with 24-hour expiry"},
    {"id": "M05", "category": "memory", "expected": "save_memory",
     "prompt": "Remember that we found a bug in the login route where the password hash comparison fails"},

    # ── Category: complex (10 prompts — multi-step, ambiguous) ───────
    {"id": "C01", "category": "complex", "expected": "write_file",
     "prompt": "Build a Flask hello world application and save it to generated_projects/flask_demo/app.py"},
    {"id": "C02", "category": "complex", "expected": "write_file",
     "prompt": "Create a Python calculator module with add subtract multiply and divide functions"},
    {"id": "C03", "category": "complex", "expected": "write_file",
     "prompt": "Write a SQLite database helper class in Python with methods for connect query and close"},
    {"id": "C04", "category": "complex", "expected": "write_file",
     "prompt": "Generate a pytest test file for a calculator module that tests all four operations"},
    {"id": "C05", "category": "complex", "expected": "write_file",
     "prompt": "Create a Python script that reads a JSON file and prints each key-value pair"},
    {"id": "C06", "category": "complex", "expected": "bash_exec",
     "prompt": "Install the requests library in the current virtual environment"},
    {"id": "C07", "category": "complex", "expected": "write_file",
     "prompt": "Write a simple logging configuration file for a Flask app"},
    {"id": "C08", "category": "complex", "expected": "read_file",
     "prompt": "Look at the current orchestrator code and tell me how many stages it has"},
    {"id": "C09", "category": "complex", "expected": "write_file",
     "prompt": "Create a basic Dockerfile for a Python Flask application"},
    {"id": "C10", "category": "complex", "expected": "list_directory",
     "prompt": "Give me an overview of the project structure"},

    # ── Category: edge_cases (5 prompts — tricky phrasing) ───────────
    {"id": "E01", "category": "edge_cases", "expected": "write_file",
     "prompt": "Can you make a file? I want it to be called output.txt and have the text done in it"},
    {"id": "E02", "category": "edge_cases", "expected": "list_directory",
     "prompt": "What's here?"},
    {"id": "E03", "category": "edge_cases", "expected": "bash_exec",
     "prompt": "echo the word HERMES to the terminal"},
    {"id": "E04", "category": "edge_cases", "expected": "read_file",
     "prompt": "let me see main.py"},
    {"id": "E05", "category": "edge_cases", "expected": "write_file",
     "prompt": "write hello world python"},
]

class PromptReliabilityTester:
    def __init__(self, model: str = "qwen2.5-coder:7b"):
        self.model = model
        self.results: list[PromptTestResult] = []

    def _build_test_system_prompt(self, tool_descriptions: str) -> str:
        from core.prompt_builder import PromptContext, build_system_prompt
        from tools.registry import tool_schema_for_prompt, list_tools
        from core.intent_classifier import IntentClassifier

        classifier = IntentClassifier("skills/")
        skill_ids = []  # No skill injection for baseline test
        ctx = PromptContext(
            user_task="",  # Will be set per prompt
            mode="auto",
            available_tools=list_tools(),
            tool_descriptions=tool_descriptions,
            memory_context="",
            skill_context="",
            active_skill_name="none"
        )
        return build_system_prompt(ctx)

    def _try_parse_response(self, response: str) -> tuple[bool, Optional[dict], Optional[str]]:
        """Attempt to parse a Tier 1 response as JSON. Returns (success, parsed_dict, failure_reason)."""
        original = response

        # ── Attempt 1: direct parse ───────────────────────────────────────────
        try:
            parsed = json.loads(response.strip())
            if "tool" in parsed and "parameters" in parsed:
                return True, parsed, None
            else:
                return False, None, f"JSON valid but missing required keys. Keys found: {list(parsed.keys())}"
        except json.JSONDecodeError:
            pass

        # ── Attempt 2: strip markdown fences ─────────────────────────────────
        cleaned = re.sub(r'^```json\s*', '', response.strip())
        cleaned = re.sub(r'^```\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned).strip()
        try:
            parsed = json.loads(cleaned)
            if "tool" in parsed and "parameters" in parsed:
                return True, parsed, "parsed_after_fence_strip"
            else:
                return False, None, f"JSON valid after fence strip but missing keys: {list(parsed.keys())}"
        except json.JSONDecodeError:
            pass

        # ── Attempt 3: extract first JSON object ─────────────────────────────
        json_pattern = re.search(r'\{[^{}]*"tool"[^{}]*"parameters"[^{}]*\}', response, re.DOTALL)
        if json_pattern:
            try:
                parsed = json.loads(json_pattern.group())
                return True, parsed, "parsed_via_extraction"
            except json.JSONDecodeError:
                pass

        # ── Categorise failure reason ─────────────────────────────────────────
        if response.strip().startswith("I ") or response.strip().startswith("Sure"):
            reason = "model_responded_with_plain_text"
        elif "```" in response:
            reason = "json_inside_markdown_but_unparseable"
        elif len(response.strip()) < 10:
            reason = "response_too_short"
        elif response.count("{") == 0:
            reason = "no_json_object_found_at_all"
        elif response.count('"tool"') == 0:
            reason = "json_found_but_no_tool_key"
        else:
            reason = "json_malformed_unparseable"

        return False, None, reason

    async def run_test(self, test_case: dict, ollama_client) -> PromptTestResult:
        from tools.registry import tool_schema_for_prompt

        result = PromptTestResult(
            prompt_id=test_case["id"],
            user_prompt=test_case["prompt"],
            category=test_case["category"],
            expected_tool=test_case.get("expected")
        )

        system_prompt = self._build_test_system_prompt(tool_schema_for_prompt())
        # Override user_task in the prompt context for this specific prompt
        system_prompt = system_prompt  # Already built above

        start = time.monotonic()
        try:
            response = await ollama_client.generate(
                model=self.model,
                prompt=f"Task: {test_case['prompt']}",
                system=system_prompt,
                keep_alive=0
            )
            result.latency_seconds = time.monotonic() - start
            result.raw_response = response
            result.response_length = len(response)
            
            success, parsed, failure_reason = self._try_parse_response(response)
            result.parsed_successfully = success
            result.failure_reason = failure_reason
            
            if success and parsed:
                result.actual_tool = parsed.get("tool")
                result.tool_correct = (result.actual_tool == result.expected_tool)
            
        except Exception as e:
            result.latency_seconds = time.monotonic() - start
            result.parsed_successfully = False
            result.failure_reason = f"generation_error: {type(e).__name__}: {str(e)[:100]}"

        self.results.append(result)
        return result

    async def run_all(self, ollama_client) -> dict:
        print(f"\nRunning {len(TEST_PROMPTS)} prompts through {self.model}...")
        print("=" * 70)

        for i, test_case in enumerate(TEST_PROMPTS):
            result = await self.run_test(test_case, ollama_client)
            
            # Safe character output check to prevent UnicodeEncodeError in Windows cmd/powershell
            status_char = "PASS" if result.parsed_successfully else "FAIL"
            
            tool_status = ""
            if result.parsed_successfully:
                tool_status_char = "OK" if result.tool_correct else "WRONG"
                tool_status = f" | tool={tool_status_char} ({result.actual_tool})"
            else:
                tool_status = f" | FAIL: {result.failure_reason}"
            
            try:
                print(f"[{i+1:02d}/{len(TEST_PROMPTS)}] {result.prompt_id} {status_char} "
                      f"{result.category:<12} {result.latency_seconds:.1f}s{tool_status}")
            except UnicodeEncodeError:
                # Absolute fallback
                print(f"[{i+1:02d}/{len(TEST_PROMPTS)}] {result.prompt_id} {status_char} "
                      f"{result.category} {result.latency_seconds:.1f}s")
            
            # Brief pause to avoid hammering Ollama
            await asyncio.sleep(0.5)

        return self.generate_report()

    def generate_report(self) -> dict:
        total = len(self.results)
        parsed_ok = sum(1 for r in self.results if r.parsed_successfully)
        tool_correct = sum(1 for r in self.results if r.tool_correct)
        parse_rate = parsed_ok / total if total > 0 else 0
        tool_rate = tool_correct / total if total > 0 else 0

        # Failure analysis
        failures_by_reason: dict[str, list[str]] = {}
        for r in self.results:
            if not r.parsed_successfully and r.failure_reason:
                failures_by_reason.setdefault(r.failure_reason, []).append(r.prompt_id)

        # Per-category breakdown
        categories = {}
        for r in self.results:
            cat = r.category
            if cat not in categories:
                categories[cat] = {"total": 0, "parsed": 0}
            categories[cat]["total"] += 1
            if r.parsed_successfully:
                categories[cat]["parsed"] += 1

        # Latency stats
        latencies = [r.latency_seconds for r in self.results if r.latency_seconds > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        max_latency = max(latencies) if latencies else 0

        report = {
            "model": self.model,
            "total_prompts": total,
            "parsed_successfully": parsed_ok,
            "parse_rate": parse_rate,
            "tool_correct": tool_correct,
            "tool_accuracy_rate": tool_rate,
            "avg_latency_seconds": round(avg_latency, 2),
            "max_latency_seconds": round(max_latency, 2),
            "failures_by_reason": {k: len(v) for k, v in failures_by_reason.items()},
            "failed_prompt_ids": [r.prompt_id for r in self.results if not r.parsed_successfully],
            "per_category": {
                cat: {
                    "total": data["total"],
                    "parsed": data["parsed"],
                    "rate": data["parsed"] / data["total"] if data["total"] > 0 else 0
                }
                for cat, data in categories.items()
            }
        }

        # Save detailed report to file
        report_path = Path("data/prompt_reliability_report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        return report

    def print_report(self, report: dict) -> None:
        print("\n" + "=" * 70)
        print("PROMPT RELIABILITY REPORT")
        print("=" * 70)
        print(f"Model:              {report['model']}")
        print(f"Total prompts:      {report['total_prompts']}")
        print(f"Parsed OK:          {report['parsed_successfully']}/{report['total_prompts']} "
              f"({report['parse_rate']*100:.1f}%)")
        print(f"Tool correct:       {report['tool_correct']}/{report['total_prompts']} "
              f"({report['tool_accuracy_rate']*100:.1f}%)")
        print(f"Avg latency:        {report['avg_latency_seconds']:.2f}s")
        print(f"Max latency:        {report['max_latency_seconds']:.2f}s")

        if report["failures_by_reason"]:
            print(f"\nFailure breakdown:")
            for reason, count in sorted(report["failures_by_reason"].items(), key=lambda x: -x[1]):
                print(f"  {count:3d} x {reason}")

        print(f"\nPer-category results:")
        for cat, data in report["per_category"].items():
            # Use ascii characters for progress bars to avoid UnicodeEncodeError in Windows cmd
            bar_filled = int(data["rate"] * 20)
            bar = "#" * bar_filled + "-" * (20 - bar_filled)
            print(f"  {cat:<14} [{bar}] {data['parsed']}/{data['total']} ({data['rate']*100:.0f}%)")

        if report["failed_prompt_ids"]:
            print(f"\nFailed prompt IDs: {', '.join(report['failed_prompt_ids'])}")

        print("\n" + "=" * 70)
        TARGET = 0.90
        if report["parse_rate"] >= TARGET:
            print(f"RESULT: PASS -- Parse rate {report['parse_rate']*100:.1f}% >= {TARGET*100:.0f}% target")
            print("System prompt is reliable enough for production use.")
        else:
            gap = TARGET - report["parse_rate"]
            print(f"RESULT: FAIL -- Parse rate {report['parse_rate']*100:.1f}% is {gap*100:.1f}% below {TARGET*100:.0f}% target")
            print("Action required: see Prompt 2 for system prompt hardening instructions.")
        print("=" * 70)
        print(f"\nDetailed report saved to: data/prompt_reliability_report.json")

async def main():
    from models.ollama_client import OllamaClient, OllamaConnectionError
    
    client = OllamaClient()
    if not await client.is_running():
        print("ERROR: Ollama is not running. Start it with: ollama serve")
        sys.exit(1)
    
    models = await client.list_models()
    if not any("qwen2.5-coder" in m for m in models):
        print("ERROR: qwen2.5-coder:7b not found. Run: ollama pull qwen2.5-coder:7b")
        sys.exit(1)
    
    tester = PromptReliabilityTester()
    report = await tester.run_all(client)
    tester.print_report(report)
    
    # Exit with non-zero if below target
    sys.exit(0 if report["parse_rate"] >= 0.90 else 1)

if __name__ == "__main__":
    asyncio.run(main())
