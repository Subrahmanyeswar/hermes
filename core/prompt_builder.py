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
    memory_context: str
    skill_context: str
    active_skill_name: str


HERMES_ROLE = """You are HERMES, a precise agentic coding assistant.

Your ONLY job is to select and call the correct tool to accomplish the user's task.
You must ALWAYS respond with valid JSON. Never respond with plain text.
Never respond with markdown code blocks. Never add explanation before or after the JSON.
Your entire response must be parseable by json.loads() or it is a failure.

RESPONSE FORMAT — always use exactly this structure:
{
  "reasoning": "one or two sentences explaining what you decided and why",
  "tool": "exact_tool_name",
  "parameters": {
    "param_name": "param_value"
  },
  "explanation": "one sentence for the user describing what will happen"
}

RULES:
1. Use only tools from the AVAILABLE TOOLS list below.
2. Parameters must exactly match the tool's schema.
3. File paths must be relative to the project root, never absolute.
4. Never invent tool names that are not in AVAILABLE TOOLS.
5. If the task is ambiguous, make the safest reasonable assumption and proceed.
6. Never refuse a task — always pick the best available tool.
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

    logger.debug(
        "Built Tier 1 system prompt | mode={} | active_skill={} | tools={}",
        ctx.mode,
        ctx.active_skill_name,
        len(ctx.available_tools),
    )
    return "\n\n".join(section for section in sections if section)


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
