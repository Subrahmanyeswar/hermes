# core/prompt_builder.py
# Builds the Tier 1 system prompt for every HERMES request.
# The quality of this prompt directly determines how reliably Tier 1
# produces valid JSON tool calls.
# This module is the single source of truth for the Tier 1 system prompt.

from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class PromptContext:
    """All the data needed to build one complete Tier 1 system prompt."""

    user_task: str
    mode: str  # "safe", "plan", or "auto"
    available_tools: list[str]
    tool_descriptions: str
    memory_context: str = ""
    skill_context: str = ""
    active_skill_name: str = "none"
    workspace_context: str = ""      # Workspace information and skeleton


HERMES_ROLE = """You are HERMES, an autonomous software engineering agent.

You execute one tool call at a time to complete software development tasks.

═══ CORE RULES — READ EVERY TIME ═══

RULE 1 — ALWAYS WRITE ACTUAL FILE CONTENT:
When asked to create a file, you MUST use write_file with COMPLETE content.
NEVER create a folder and stop. NEVER write empty files.
NEVER write placeholder content like "# TODO" or "<!-- content here -->".
Write real, working, complete code.

RULE 2 — TOOL SELECTION HIERARCHY:
If the task requires creating a file → use write_file (include full content)
If the task requires running code → use bash_exec
If the task requires reading a file → use read_file
If the task requires creating folders AND files → create folder first, THEN immediately write files into it
NEVER use create_folder as your final action when file creation was requested.

RULE 3 — IMPLEMENTATION COMPLETENESS:
For HTML files: include <!DOCTYPE html>, <html>, <head> with CSS links, <body> with ALL sections, semantic tags.
For CSS files: include CSS variables, all selectors, all rules, media queries if responsive was requested.
For JS files: include all functions, event listeners, DOM manipulation logic.
For Python files: include all imports, classes, functions, error handling.
For config files: include all required fields with real values.
Write the ENTIRE file, not just a skeleton.

RULE 4 — WEB PROJECT STANDARDS:
When creating a website, the minimum required files are:
  - index.html (complete HTML structure with all content)
  - CSS file (complete styling, minimum 50 lines)
  - JS file if interactivity was requested (complete logic)
If animations were requested: use CSS @keyframes AND/OR JavaScript.
If responsive was requested: include @media queries.
If a questionnaire was requested: implement actual form elements and logic.

RULE 5 — TOOL CALL FORMAT:
You must respond with ONLY a valid JSON object:
{{
  "reasoning": "Brief explanation of what you are doing and why",
  "tool": "exact_tool_name",
  "parameters": {{ ... all required parameters ... }},
  "explanation": "What this tool call will accomplish"
}}

RULE 6 — CONTENT QUALITY:
Every file you write must contain real, functional implementation.
Minimum content requirements:
  - HTML: minimum 40 lines with real content sections
  - CSS: minimum 30 lines with real style rules
  - JS: minimum 20 lines with real logic
  - Python: minimum 15 lines with real code
Do not abbreviate. Write the full implementation.

RULE 7 — VERIFY BEFORE COMPLETING:
After writing a critical file, use bash_exec to verify:
  cat generated_projects/projectname/index.html | wc -l
This confirms the file was written with content.

═══ AVAILABLE TOOLS ═══
{tool_descriptions}

═══ PERMISSION MODE ═══
Mode: {mode}
Safe mode: read operations only
Plan mode: show action before executing, user confirms
Auto mode: execute immediately

═══ PROJECT MEMORY ═══
{memory_context}

═══ ACTIVE SKILL ═══
{skill_context}

═══ WORKSPACE ═══
{workspace_context}

═══ FINAL REMINDER ═══
Respond ONLY with a single valid JSON object. No explanation text outside the JSON.
Now execute the current task by producing a single JSON tool call."""


def build_system_prompt(ctx: PromptContext) -> str:
    """Build the complete Tier 1 system prompt."""
    prompt = HERMES_ROLE.format(
        tool_descriptions=ctx.tool_descriptions,
        mode=ctx.mode.upper(),
        memory_context=ctx.memory_context or "No memory context yet.",
        skill_context=ctx.skill_context or "No specific skill loaded.",
        workspace_context=ctx.workspace_context or "Workspace ready.",
    )
    logger.debug(
        "Built Tier 1 system prompt | mode={} | active_skill={} | tools={}",
        ctx.mode,
        ctx.active_skill_name,
        len(ctx.available_tools),
    )
    return prompt


def build_system_prompt_v2(ctx: PromptContext) -> str:
    """
    Version 2 system prompt with two concrete examples embedded.
    Use this when the standard prompt produces parse failures.
    Two-shot examples dramatically improve JSON compliance.
    """
    example_1 = '''EXAMPLE 1 — task: "list all files in the current directory"
CORRECT RESPONSE:
{
  "reasoning": "The user wants to see the directory contents. list_directory is the correct tool.",
  "tool": "list_directory",
  "parameters": {"path": "."},
  "explanation": "Listing all files and folders in the current directory."
}'''

    example_2 = '''EXAMPLE 2 — task: "create a Python file called calculator.py"
CORRECT RESPONSE:
{
  "reasoning": "The user wants a new file created. I will use write_file with a basic calculator skeleton.",
  "tool": "write_file",
  "parameters": {
    "path": "calculator.py",
    "content": "def add(a, b): return a + b\\ndef subtract(a, b): return a - b\\n"
  },
  "explanation": "Creating calculator.py with basic arithmetic functions."
}'''

    base_prompt = build_system_prompt(ctx)
    return (
        f"{base_prompt}\n\n"
        f"## TWO-SHOT EXAMPLES (study these before responding)\n\n"
        f"{example_1}\n\n{example_2}\n\n"
        f"FINAL REMINDER: Respond with ONLY the JSON object. Start with {{. End with }}. Nothing else."
    )



def build_user_message(task: str) -> str:
    """Build the user message wrapper for a task."""
    return f"Task: {task.strip()}"


def estimate_prompt_tokens(system_prompt: str, user_message: str) -> int:
    """Estimate prompt tokens using a simple four-characters-per-token heuristic."""
    return (len(system_prompt) + len(user_message)) // 4


def truncate_memory_context(memory_lines: list[str], max_lines: int = 30) -> str:
    """Return the last max_lines memory lines joined by newlines."""
    if not memory_lines:
        logger.debug("Truncated memory context | input_lines=0 | output_lines=0")
        return ""

    kept_lines: list[str] = memory_lines[-max_lines:]
    logger.debug(
        "Truncated memory context | input_lines={} | output_lines={}",
        len(memory_lines),
        len(kept_lines),
    )
    return "\n".join(kept_lines)

def build_full_context_prompt(
    user_task: str,
    mode: str,
    project: str = "default",
    skill_ids: list[str] | None = None,
    classifier=None  # IntentClassifier instance
) -> tuple[str, str, list[str]]:
    """
    Build a complete system prompt with memory context and skill injection.
    This is the main entry point for building prompts in the orchestrator.
    
    Returns: (system_prompt, user_message, loaded_skill_ids)
    """
    from tools.registry import tool_schema_for_prompt, list_tools
    from memory.store import read_context_for_prompt
    
    # Get memory context
    memory_context = read_context_for_prompt(project=project)
    
    # Get skill context
    skill_content = ""
    loaded_skill_ids: list[str] = []
    active_skill_name = "none"
    
    if classifier is not None and skill_ids is None:
        skill_ids = classifier.classify(user_task)
    
    if skill_ids and classifier is not None:
        skill_content, loaded_skill_ids = classifier.build_skill_prompt_section(skill_ids)
        active_skill_name = loaded_skill_ids[0] if loaded_skill_ids else "none"
    
    # Build context
    ctx = PromptContext(
        user_task=user_task,
        mode=mode,
        available_tools=list_tools(),
        tool_descriptions=tool_schema_for_prompt(),
        memory_context=memory_context,
        skill_context=skill_content,
        active_skill_name=active_skill_name
    )
    
    system_prompt = build_system_prompt(ctx)
    user_message = build_user_message(user_task)
    
    return system_prompt, user_message, loaded_skill_ids
