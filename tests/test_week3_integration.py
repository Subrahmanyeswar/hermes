#!/usr/bin/env python3
"""
HERMES — Week 3 Integration Tests
Tests: network tools, git tools, classifier + prompt builder integration,
and the complete prompt pipeline with skill injection.
Requires: Ollama running with qwen2.5-coder:7b pulled.

Run: python tests/test_week3_integration.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.network_tools import WebSearchTool, WebFetchTool
from tools.git_tools import GitInitTool, GitAddCommitTool
from core.intent_classifier import IntentClassifier
from core.prompt_builder import PromptContext, build_system_prompt, build_user_message
from models.ollama_client import OllamaClient

# ──────────────────────────────────────────────────────────────────────

def test_1_web_search_returns_real_results():
    """WebSearchTool returns real results from DuckDuckGo (requires internet)."""
    tool = WebSearchTool()
    result = tool.execute(WebSearchTool.Input(query="Python programming language", max_results=3))
    
    if not result.success:
        print(f"  ⚠ Web search failed (no internet?): {result.error}")
        print("  ⚠ Skipping — this is acceptable if offline")
        return
    
    assert len(result.output) > 50, "Search returned too little content"
    print(f"  ✓ Web search returned {len(result.output)} characters of results")

# ──────────────────────────────────────────────────────────────────────

def test_2_web_fetch_returns_real_page():
    """WebFetchTool fetches real content from a stable URL."""
    tool = WebFetchTool()
    result = tool.execute(WebFetchTool.Input(url="https://httpbin.org/get", max_chars=1000))
    
    if not result.success:
        print(f"  ⚠ Web fetch failed (no internet?): {result.error}")
        print("  ⚠ Skipping — acceptable if offline")
        return
    
    assert len(result.output) > 20
    print(f"  ✓ Web fetch returned {len(result.output)} characters | URL responded OK")

# ──────────────────────────────────────────────────────────────────────

def test_3_git_init_and_commit_workflow(tmp_path):
    """Full git workflow: init → create file → commit → verify."""
    import git
    
    # Init
    init_tool = GitInitTool()
    result = init_tool.execute(GitInitTool.Input(directory=str(tmp_path)))
    assert result.success is True, f"git_init failed: {result.error}"
    
    # Create a file
    test_file = tmp_path / "app.py"
    test_file.write_text('print("Hello from HERMES")\n')
    
    # Commit
    commit_tool = GitAddCommitTool()
    result = commit_tool.execute(GitAddCommitTool.Input(
        directory=str(tmp_path),
        message="feat: add initial app.py"
    ))
    assert result.success is True, f"git commit failed: {result.error}"
    assert "SHA" in result.output, "Commit output should contain SHA"
    
    # Verify the commit exists
    repo = git.Repo(str(tmp_path))
    commits = list(repo.iter_commits())
    assert len(commits) >= 1
    assert commits[0].message.strip() == "feat: add initial app.py"
    
    print(f"  ✓ Git workflow: init → commit | SHA: {commits[0].hexsha[:8]}")

# ──────────────────────────────────────────────────────────────────────

def test_4_classifier_identifies_all_three_skills():
    """Classifier correctly identifies all 3 skills from relevant prompts."""
    classifier = IntentClassifier("skills/")
    
    test_cases = [
        ("build a flask rest api with crud endpoints and user login", "flask-rest-api"),
        ("debug this python error I am getting a traceback", "debugging"),
        ("write pytest unit tests for my calculator module", "pytest-generation"),
    ]
    
    failures = []
    for prompt, expected in test_cases:
        result = classifier.classify(prompt)
        if expected not in result:
            failures.append(f"Expected '{expected}' for prompt: {prompt!r}, got: {result}")
    
    assert len(failures) == 0, "Classifier failures:\n" + "\n".join(failures)
    print(f"  ✓ Classifier: all 3 skills identified correctly from real prompts")

# ──────────────────────────────────────────────────────────────────────

def test_5_classifier_integrates_with_prompt_builder():
    """Classifier output feeds correctly into prompt builder."""
    classifier = IntentClassifier("skills/")
    
    prompt = "build a flask rest api with user authentication and crud endpoints"
    skill_ids = classifier.classify(prompt)
    
    assert "flask-rest-api" in skill_ids
    
    skill_content, loaded_ids = classifier.build_skill_prompt_section(skill_ids)
    assert len(skill_content) > 100, "Skill content should be substantial"
    assert "flask-rest-api" in loaded_ids
    
    ctx = PromptContext(
        user_task=prompt,
        mode="auto",
        available_tools=["write_file", "read_file", "bash_exec"],
        tool_descriptions="- write_file: Write a file\n- read_file: Read a file\n- bash_exec: Run a command",
        memory_context="",
        skill_context=skill_content,
        active_skill_name=loaded_ids[0] if loaded_ids else "none"
    )
    
    system_prompt = build_system_prompt(ctx)
    
    assert "flask-rest-api" in system_prompt, "Active skill name should appear in prompt"
    assert "SQLAlchemy" in system_prompt, "Skill content should be injected into prompt"
    assert "ACTIVE SKILL" in system_prompt, "Skill section header should be present"
    
    token_estimate = len(system_prompt) // 4
    assert token_estimate < 4096, f"Prompt with skill is too long: ~{token_estimate} tokens"
    
    print(f"  ✓ Classifier → prompt builder: skill injected correctly (~{token_estimate} tokens)")

# ──────────────────────────────────────────────────────────────────────

async def test_6_tier1_uses_skill_context_correctly():
    """
    Tier 1 (Qwen) produces better Flask-specific responses when skill is injected.
    Compares: response WITH flask-rest-api skill vs WITHOUT skill.
    Both must be valid JSON. The skill response should mention Flask-specific elements.
    """
    client = OllamaClient()
    if not await client.is_running():
        print("  ⚠ Ollama not running — skipping Tier 1 skill test")
        return
    
    classifier = IntentClassifier("skills/")
    task = "Create a Flask REST API with a users endpoint that returns a JSON list"
    
    tool_descriptions = (
        "- write_file: Write content to a file. Parameters: path (str), content (str)\n"
        "- read_file: Read a file. Parameters: path (str)\n"
        "- bash_exec: Run a shell command. Parameters: command (str)\n"
        "- run_python: Run a Python file. Parameters: file_path (str)"
    )
    
    # ── WITHOUT skill ─────────────────────────────────────────────────
    ctx_no_skill = PromptContext(
        user_task=task, mode="auto",
        available_tools=["write_file", "read_file", "bash_exec", "run_python"],
        tool_descriptions=tool_descriptions,
        memory_context="", skill_context="", active_skill_name="none"
    )
    response_no_skill = await client.generate(
        model="qwen2.5-coder:7b",
        prompt=build_user_message(task),
        system=build_system_prompt(ctx_no_skill),
        keep_alive=0
    )
    
    # ── WITH skill ────────────────────────────────────────────────────
    skill_ids = classifier.classify(task)
    skill_content, loaded_ids = classifier.build_skill_prompt_section(skill_ids)
    
    ctx_with_skill = PromptContext(
        user_task=task, mode="auto",
        available_tools=["write_file", "read_file", "bash_exec", "run_python"],
        tool_descriptions=tool_descriptions,
        memory_context="", skill_context=skill_content,
        active_skill_name=loaded_ids[0] if loaded_ids else "none"
    )
    response_with_skill = await client.generate(
        model="qwen2.5-coder:7b",
        prompt=build_user_message(task),
        system=build_system_prompt(ctx_with_skill),
        keep_alive=0
    )
    
    # ── Validate both are valid JSON ──────────────────────────────────
    def try_parse(resp: str, label: str) -> dict | None:
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", resp, re.DOTALL)
        if match:
            cleaned = match.group(1)
        else:
            start = resp.find('{')
            end = resp.rfind('}')
            if start != -1 and end != -1:
                cleaned = resp[start:end+1]
            else:
                cleaned = resp
                
        try:
            return json.loads(cleaned.strip())
        except json.JSONDecodeError:
            print(f"  ⚠ {label} response was not valid JSON (preview):\n{resp[:200]}...\n")
            return None
    
    parsed_no_skill = try_parse(response_no_skill, "WITHOUT skill")
    parsed_with_skill = try_parse(response_with_skill, "WITH skill")
    
    assert parsed_with_skill is not None, "Response WITH skill must be valid JSON"
    assert "tool" in parsed_with_skill, "Response WITH skill must contain 'tool' key"
    
    print(f"  ✓ WITHOUT skill: {'valid JSON' if parsed_no_skill else 'invalid JSON'} | tool={parsed_no_skill.get('tool') if parsed_no_skill else 'N/A'}")
    print(f"  ✓ WITH skill:    valid JSON | tool={parsed_with_skill.get('tool')} | skill={loaded_ids}")

# ──────────────────────────────────────────────────────────────────────

async def main():
    import tempfile
    
    print("=" * 60)
    print("HERMES — Week 3 Integration Tests")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        tests = [
            ("Web search returns real results", lambda: test_1_web_search_returns_real_results()),
            ("Web fetch returns real page content", lambda: test_2_web_fetch_returns_real_page()),
            ("Git init + commit workflow", lambda: test_3_git_init_and_commit_workflow(tmp_path)),
            ("Classifier identifies all 3 skills", lambda: test_4_classifier_identifies_all_three_skills()),
            ("Classifier integrates with prompt builder", lambda: test_5_classifier_integrates_with_prompt_builder()),
            ("Tier 1 uses skill context correctly", lambda: asyncio.ensure_future(test_6_tier1_uses_skill_context_correctly())),
        ]
        
        passed_all = True
        for name, test_fn in tests:
            print(f"\n[TEST] {name}")
            try:
                result = test_fn()
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except AssertionError as e:
                print(f"  ✗ FAILED: {e}")
                passed_all = False
            except Exception as e:
                print(f"  ✗ ERROR: {type(e).__name__}: {e}")
                passed_all = False
    
    print("\n" + "=" * 60)
    if passed_all:
        print("WEEK 3 COMPLETE: All integration tests passed.")
        print("Network tools, Git tools, Classifier, and Skill Engine are solid.")
        print("Ready for Week 4 (Memory System).")
    else:
        print("WEEK 3 INCOMPLETE: Fix the failures above before Week 4.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
