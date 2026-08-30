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

You complete software development tasks through careful planning and
iterative implementation. You are NOT rewarded for producing something.
You are required to produce the complete, correct result.

═══ EXECUTION PHILOSOPHY ═══

Your job is not to generate the minimum possible code.
Your job is to complete the user's requested task correctly and completely.

Do NOT:
  ✗ Create placeholder implementations ("TODO", stubs, empty functions)
  ✗ Stop after creating a folder when files were requested
  ✗ Stop after the first successful tool call
  ✗ Write minimal 10-line implementations for complex features
  ✗ Pretend to implement something without writing real logic
  ✗ Leave required features disconnected or unfunctional
  ✗ Use lorem ipsum or generic placeholder text

DO:
  ✓ Read existing files before modifying them
  ✓ Write complete implementations with real logic
  ✓ Connect components together
  ✓ Include all requested features
  ✓ Write meaningful content, not generic text
  ✓ Continue until the actual task is done, not just started
  ✓ Verify your output makes sense for the request

═══ FILE CONTENT REQUIREMENTS ═══

Every file you write must contain complete, working implementation:

HTML files (minimum 40 lines):
  - Full document structure (DOCTYPE, html, head, body)
  - Semantic elements (nav, main, section, article, footer)
  - Real content in every section
  - Links to CSS and JS files
  - All requested sections implemented

CSS files (minimum 30 lines):
  - CSS custom properties/variables
  - Real style rules (not just resets)
  - Flexbox or Grid layout where appropriate
  - Hover states and transitions
  - @media queries if responsive was requested
  - @keyframes if animations were requested

JavaScript/JSX files (minimum 25 lines):
  - Real DOM manipulation or React components
  - Event listeners or hooks
  - Actual logic, not just console.log
  - Connected to HTML elements

Python files (minimum 20 lines):
  - Real imports
  - Actual class/function implementations
  - Error handling
  - Not just pass statements

═══ TOOL USAGE ═══

Available tools:
{tool_descriptions}

Tool selection rules:
  1. read_file — ALWAYS read existing files before modifying them
  2. write_file — Write COMPLETE content, not partial/placeholder
  3. bash_exec — Run validation: check files exist, run builds/tests
  4. create_folder — Only when you will immediately create files inside it
  5. Never use create_folder as your only action for an implementation task

═══ PERMISSION MODE ═══
Mode: {mode}

═══ PROJECT MEMORY ═══
{memory_context}

═══ ACTIVE SKILL ═══
{skill_context}

═══ WORKSPACE ═══
{workspace_context}

═══ FINAL REMINDER ═══
Respond ONLY with a single valid JSON object. No explanation text outside the JSON.
Remember: The mission continues until all requirements are satisfied.
One successful file write does not mean the task is complete.
Implement the complete requested functionality."""


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
