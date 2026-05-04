# tools/memory_tools.py
# Memory tools for HERMES — tools that Tier 1 can explicitly call.
# save_memory: Tier 1 requests saving a specific fact. Still requires exit_code=0 confirmation.
# read_memory: Tier 1 reads a Layer 2 topic file when following a [DETAIL] pointer.
# These are separate from the automatic extraction (memory/extractor.py).

from pydantic import BaseModel, Field
from typing import Literal
from tools.base import BaseTool, ToolResult
from tools.registry import tool
from memory.types import MemoryFact, MemoryState, FactType
from memory.store import write_fact, read_layer2_topic, read_context_for_prompt
from loguru import logger

@tool(
    name="save_memory",
    description="Save a specific fact to project memory. Only use for important project decisions that should persist across sessions.",
    permissions=["memory_write"],
    risk_score=0.1,
    blocked_in=[]
)
class SaveMemoryTool(BaseTool):
    class Input(BaseModel):
        fact_type: Literal["FACT", "BUG", "TASK_DONE", "BLOCKED", "DETAIL"] = Field(default="FACT")
        content: str = Field(..., description="The fact to remember — max 150 characters", min_length=5, max_length=150)
        project: str = Field(default="default", description="Project name this fact belongs to")

    def execute(self, inp: Input) -> ToolResult:
        fact = MemoryFact(fact_type=FactType[inp.fact_type], content=inp.content)
        fact.confirm(tool_name="save_memory", exit_code=0)
        success = write_fact(fact, project=inp.project)
        return ToolResult(
            success=success,
            output=f"Saved [{inp.fact_type}]: {inp.content}",
            exit_code=0 if success else 1
        )

@tool(
    name="read_memory",
    description="Read a Layer 2 topic file for detailed project information. Use when MEMORY.md has a [DETAIL] pointer.",
    permissions=["memory_read"],
    risk_score=0.0,
    blocked_in=[]
)
class ReadMemoryTool(BaseTool):
    class Input(BaseModel):
        topic_name: str = Field(..., description="Name of the topic file to read, without .md extension", min_length=1, max_length=100)
        project: str = Field(default="default")

    def execute(self, inp: Input) -> ToolResult:
        content = read_layer2_topic(inp.project, inp.topic_name)
        if content is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Topic file '{inp.topic_name}' not found for project '{inp.project}'",
                exit_code=1
            )
        return ToolResult(success=True, output=content, exit_code=0)
