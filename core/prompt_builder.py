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


HERMES_ROLE = """You are HERMES, a precise agentic coding assistant. Your ONLY job is to call tools.

CRITICAL RULE — READ THIS FIRST:
You must ALWAYS respond with a single valid JSON object and NOTHING ELSE.
No words before the JSON. No words after the JSON. No markdown. No explanation.
Your entire response, from the very first character to the very last, must be valid JSON.

If you respond with anything other than a JSON object, the system will crash.

MANDATORY RESPONSE FORMAT — copy this structure exactly:
{
  "reasoning": "one or two sentences explaining what you are doing and why",
  "tool": "exact_tool_name_from_the_list_below",
  "parameters": {
    "param_name": "param_value"
  },
  "explanation": "one sentence for the user"
}

CONCRETE EXAMPLE — for the task "create a hello.py file":
{
  "reasoning": "The user wants to create a Python file. I will use write_file with the correct path and content.",
  "tool": "write_file",
  "parameters": {
    "path": "hello.py",
    "content": "print('hello world')\\n"
  },
  "explanation": "Creating hello.py with a print statement."
}

RULES FOR TOOL SELECTION:
1. Use ONLY tools from the AVAILABLE TOOLS section below.
2. Tool names must be spelled exactly as shown — no variations.
3. Parameters must match the tool's schema exactly.
4. File paths must be relative to the project root, never absolute.
5. If you are unsure which tool to use, pick the most appropriate one and explain in reasoning.
6. Never refuse a task. Always pick a tool and attempt the action.

RULES FOR JSON OUTPUT:
7. Start your response with the opening brace { immediately — no preamble.
8. End your response with the closing brace } — nothing after it.
9. All string values must use standard double quotes (\"). NEVER use triple-quotes (\'\'\' or \"\"\") or raw unescaped multiline strings.
10. All newlines inside string values MUST be escaped as \n.
11. The parameters field must always be a JSON object {}, even if empty: "parameters": {}

TOOL DISAMBIGUATION — follow these rules when choosing between similar tools:
- "create a folder/directory" → use create_folder (NOT write_file or bash_exec)
- "count lines in a file" or "wc -l" (numeric line/character counting ONLY) → use bash_exec (NOT read_file)
- "look at code", "analyze code", "show me the code", or questions about code structures/contents (e.g. "how many stages/functions/routes/classes are in the code") → use read_file (NOT bash_exec, as wc -l cannot count semantic stages)
- "pip install" or "install a package" → use bash_exec (NOT run_python)
- "git log" or "show commits" → use bash_exec (NOT a git tool — there is no git_log tool)
- "build/create/write a file with code" → use write_file (NOT create_folder)
- "run a .py script" → use run_python (NOT bash_exec)
- "run tests" or "pytest" → use run_tests (NOT run_python or bash_exec)
- "remember" or "keep in mind" or "note that" → use save_memory (NOT read_memory)
- "recall" or "what did we save" or "read memory" → use read_memory (NOT save_memory)
"""


def build_system_prompt(ctx: PromptContext) -> str:
    """Build the complete Tier 1 system prompt from prompt context."""
    sections: list[str] = [HERMES_ROLE]

    if ctx.skill_context:
        sections.append(f"## ACTIVE SKILL: {ctx.active_skill_name}\n\n{ctx.skill_context}")

    if ctx.memory_context:
        sections.append(
            "## PROJECT MEMORY\n"
            "The following facts are known about the current project:\n\n"
            f"{ctx.memory_context}"
        )

    sections.append(
        "## AVAILABLE TOOLS\n"
        "You may only use these tools:\n\n"
        f"{ctx.tool_descriptions}"
    )

    mode_instructions: dict[str, str] = {
        "safe": "You are in SAFE MODE. Only read operations are permitted. You may NOT write files, execute commands, or modify anything.",
        "plan": "You are in PLAN MODE. Show your tool call before executing. The user will confirm before any action is taken.",
        "auto": "You are in AUTO MODE. Execute tool calls directly after security validation.",
    }
    mode_instruction: str = mode_instructions.get(ctx.mode, mode_instructions["safe"])
    sections.append(f"## CURRENT MODE: {ctx.mode.upper()}\n{mode_instruction}")

    sections.append(
        "Remember: respond ONLY with valid JSON matching the format above. Nothing else."
    )

    # Add a final reminder at the end — models attend to both start and end of long prompts
    reminder_section = (
        "\n\nFINAL REMINDER: Your response must start with { and end with }. "
        "Valid JSON only. No other text."
    )
    sections.append(reminder_section)

    logger.debug(
        "Built Tier 1 system prompt | mode={} | active_skill={} | tools={}",
        ctx.mode,
        ctx.active_skill_name,
        len(ctx.available_tools),
    )
    return "\n\n".join(section for section in sections if section)


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

    sections = [
        HERMES_ROLE,
        f"## TWO-SHOT EXAMPLES (study these before responding)\n\n{example_1}\n\n{example_2}",
    ]

    if ctx.skill_context:
        sections.append(f"## ACTIVE SKILL: {ctx.active_skill_name}\n\n{ctx.skill_context}")

    if ctx.memory_context:
        sections.append(f"## PROJECT MEMORY\n\n{ctx.memory_context}")

    sections.append(f"## AVAILABLE TOOLS\n\n{ctx.tool_descriptions}")
    sections.append(
        f"## CURRENT MODE: {ctx.mode.upper()}\n"
        + {
            "safe": "SAFE MODE: Read-only. No write, execute, or git operations.",
            "plan": "PLAN MODE: Show tool call first. User confirms before execution.",
            "auto": "AUTO MODE: Execute after security validation."
        }.get(ctx.mode, "AUTO MODE")
    )
    sections.append(
        "FINAL REMINDER: Respond with ONLY the JSON object. "
        "Start with {. End with }. Nothing else."
    )

    return "\n\n".join(sections)



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
