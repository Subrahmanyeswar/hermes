# memory/types.py
# Shared types for the HERMES three-layer memory system.
# All memory modules import from here — never define memory types elsewhere.
# Three-layer hierarchy:
#   Layer 1: MEMORY.md — always in Tier 1 context window (pointers + summaries)
#   Layer 2: topic files in data/memory/ — loaded on demand via [DETAIL] pointers
#   Layer 3: session JSONL logs in data/sessions/ — search only, never read into context

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional

class MemoryState(Enum):
    """
    The three states of the memory state machine.
    A fact can only move forward through states — never backward.
    PROPOSED → CONFIRMED → PERSISTED
    """
    PROPOSED = "proposed"    # Model suggested this fact. Not written yet.
    CONFIRMED = "confirmed"  # OS confirmed tool exit_code=0. Eligible to write.
    PERSISTED = "persisted"  # Written to MEMORY.md. Visible next session.


class FactType(Enum):
    """
    The six types of facts stored in MEMORY.md Layer 1.
    Each type has a specific prefix used in the file.
    """
    FACT = "FACT"           # [FACT]: A verified technical fact about the project
    BUG = "BUG"             # [BUG]: A known bug and its status
    TASK_DONE = "TASK_DONE" # [TASK_DONE]: A completed task with tools used
    BLOCKED = "BLOCKED"     # [BLOCKED]: A task blocked on a dependency
    DETAIL = "DETAIL"       # [DETAIL]: Pointer to a Layer 2 topic file
    STALE = "STALE"         # [STALE]: A fact superseded by a newer contradicting fact


@dataclass
class MemoryFact:
    """
    A single fact in the memory system.
    Created in PROPOSED state. Moves to CONFIRMED only after tool success.
    Moves to PERSISTED only after write_memory_fact() succeeds.
    """
    fact_type: FactType
    content: str                          # The fact text — max 150 chars enforced on write
    state: MemoryState = MemoryState.PROPOSED
    project: str = "default"             # Which project this fact belongs to
    created_at: datetime = field(default_factory=datetime.now)
    confirmed_at: Optional[datetime] = None
    persisted_at: Optional[datetime] = None
    source_tool: Optional[str] = None    # Which tool confirmed this fact (e.g. "write_file")
    source_exit_code: Optional[int] = None  # exit code that confirmed this

    def confirm(self, tool_name: str, exit_code: int) -> None:
        """
        Move fact from PROPOSED to CONFIRMED.
        Must only be called when exit_code == 0.
        Raises ValueError if exit_code != 0 or if fact is not in PROPOSED state.
        """
        if exit_code != 0:
            raise ValueError(
                f"Cannot confirm fact — tool '{tool_name}' returned exit_code={exit_code}. "
                f"Only exit_code=0 can confirm a memory fact."
            )
        if self.state != MemoryState.PROPOSED:
            raise ValueError(
                f"Cannot confirm fact — it is already in state '{self.state.value}'. "
                f"Facts can only be confirmed from PROPOSED state."
            )
        self.state = MemoryState.CONFIRMED
        self.confirmed_at = datetime.now()
        self.source_tool = tool_name
        self.source_exit_code = exit_code

    def persist(self) -> None:
        """
        Move fact from CONFIRMED to PERSISTED.
        Raises ValueError if fact is not in CONFIRMED state.
        """
        if self.state != MemoryState.CONFIRMED:
            raise ValueError(
                f"Cannot persist fact — it is in state '{self.state.value}'. "
                f"Facts must be CONFIRMED before they can be PERSISTED."
            )
        self.state = MemoryState.PERSISTED
        self.persisted_at = datetime.now()

    def to_memory_line(self) -> str:
        """
        Convert this fact to a MEMORY.md line format.
        Format: [FACT_TYPE]: content text
        Enforces the 150-character limit on the content portion.
        Raises ValueError if content exceeds 150 characters.
        """
        if len(self.content) > 150:
            raise ValueError(
                f"Memory fact content exceeds 150-character limit ({len(self.content)} chars): "
                f"{self.content[:60]}..."
            )
        return f"[{self.fact_type.value}]: {self.content}"

    @staticmethod
    def from_memory_line(line: str, project: str = "default") -> Optional[MemoryFact]:
        """
        Parse a MEMORY.md line back into a MemoryFact.
        Returns None if the line does not match any known fact type format.
        Lines starting with # or empty lines return None.
        """
        line = line.strip()
        if not line or line.startswith('#'):
            return None
        for fact_type in FactType:
            prefix = f"[{fact_type.value}]: "
            if line.startswith(prefix):
                content = line[len(prefix):]
                return MemoryFact(
                    fact_type=fact_type,
                    content=content,
                    state=MemoryState.PERSISTED,  # Lines in file are already persisted
                    project=project
                )
        return None


@dataclass
class MemoryIndex:
    """
    The parsed contents of a MEMORY.md file.
    Represents all facts for one project.
    """
    project: str
    facts: list[MemoryFact] = field(default_factory=list)
    last_updated: Optional[datetime] = None

    def get_by_type(self, fact_type: FactType) -> list[MemoryFact]:
        """Return all facts of a specific type."""
        return [f for f in self.facts if f.fact_type == fact_type]

    def get_all_lines(self) -> list[str]:
        """Return all facts as MEMORY.md formatted lines."""
        return [f.to_memory_line() for f in self.facts]

    def find_contradicting(self, new_content: str, fact_type: FactType) -> Optional[MemoryFact]:
        """
        Find an existing fact that might contradict the new content.
        Simple heuristic: same fact_type and at least one common significant word (>4 chars).
        Returns the first contradicting fact found, or None.
        """
        new_words = {w.lower() for w in new_content.split() if len(w) > 4}
        for fact in self.facts:
            if fact.fact_type != fact_type:
                continue
            existing_words = {w.lower() for w in fact.content.split() if len(w) > 4}
            if new_words & existing_words:  # intersection — shared significant words
                return fact
        return None
