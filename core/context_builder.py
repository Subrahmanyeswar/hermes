# core/context_builder.py
# ContextBuilder — intelligent context assembly for HERMES task execution.
#
# Three-tier context assembly strategy:
#   Tier A — Always present (every task):
#              workspace skeleton + framework detection + current task description
#   Tier B — Task-relevant (selected per task):
#              file signatures for files the task will touch
#              recent memory facts (top 5)
#              previous task results (last 2)
#   Tier C — On demand (only when explicitly needed):
#              full file content for files the task must read/modify
#
# Budget enforcement:
#   Total context budget: 6000 tokens (conservative for Qwen 7B @ Q4_K_M)
#   Tier A: ~800 tokens (fixed overhead)
#   Tier B: ~2000 tokens (variable, trimmed to fit)
#   Tier C: ~3200 tokens (remainder, largest files first)
#   System prompt + tool schema: ~2000 tokens (reserved, not counted here)
#
# This ensures the model always has room to generate 1500+ output tokens.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from loguru import logger

from core.workspace import WorkspaceManager
from core.mission_planner import MissionTask, Mission


# ── Token budget constants ────────────────────────────────────────────────────
TOKEN_BUDGET_TOTAL: int    = 6000
TOKEN_BUDGET_TIER_A: int   = 800
TOKEN_BUDGET_TIER_B: int   = 2000
TOKEN_BUDGET_TIER_C: int   = 3200

# Approximate token conversion: 1 token ≈ 3.8 chars for code
CHARS_PER_TOKEN: float = 3.8


def estimate_tokens(text: str) -> int:
    """Fast token estimate. Accurate enough for budget enforcement."""
    return max(1, int(len(text) / CHARS_PER_TOKEN))


@dataclass
class ContextSection:
    """One section of the assembled context with metadata."""
    name: str
    content: str
    token_estimate: int
    tier: str      # "A", "B", or "C"

    @classmethod
    def from_content(cls, name: str, content: str, tier: str) -> "ContextSection":
        return cls(
            name=name,
            content=content,
            token_estimate=estimate_tokens(content),
            tier=tier,
        )


@dataclass
class AssembledContext:
    """The fully assembled context ready for injection into the system prompt."""
    sections: list[ContextSection] = field(default_factory=list)
    total_tokens: int = 0
    budget_used_pct: float = 0.0
    truncated_sections: list[str] = field(default_factory=list)

    def to_string(self) -> str:
        """Render all sections into a single string for LLM injection."""
        parts: list[str] = []
        for section in self.sections:
            if section.content.strip():
                parts.append(f"\n{'─' * 50}")
                parts.append(f"[{section.name}]")
                parts.append(section.content.strip())
        return "\n".join(parts)

    def summary(self) -> str:
        return (
            f"Context: {self.total_tokens}/{TOKEN_BUDGET_TOTAL} tokens used "
            f"({self.budget_used_pct:.0f}%) | "
            f"{len(self.sections)} sections | "
            f"truncated: {self.truncated_sections or 'none'}"
        )


class ContextBuilder:
    """
    Builds optimal LLM context for HERMES task execution.
    Called by MissionRunner before each Orchestrator.run() call.

    Usage:
        builder = ContextBuilder(workspace_manager)
        context = builder.build(task, mission, memory_context="...")
        enriched_prompt = context.to_string() + f"\n\nTASK: {task.description}"
    """

    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace

    def build(
        self,
        task: MissionTask,
        mission: Mission,
        memory_context: str = "",
        previous_outputs: Optional[list[str]] = None,
        error_context: str = "",
    ) -> AssembledContext:
        """
        Assemble the complete context for a task, respecting token budgets.

        Args:
            task:             The task about to be executed
            mission:          The full mission (for completed task context)
            memory_context:   Content from MEMORY.md injection
            previous_outputs: Last N tool outputs for continuity
            error_context:    Error from previous attempt (repair cycle)
        """
        ctx = AssembledContext()
        remaining_budget = TOKEN_BUDGET_TOTAL

        # ── TIER A: Always-present context ───────────────────────────────────
        tier_a_sections = self._build_tier_a(task, mission)
        for section in tier_a_sections:
            if remaining_budget - section.token_estimate > 0:
                ctx.sections.append(section)
                ctx.total_tokens += section.token_estimate
                remaining_budget -= section.token_estimate
            else:
                ctx.truncated_sections.append(section.name)

        # ── TIER B: Task-relevant context ─────────────────────────────────────
        tier_b_sections = self._build_tier_b(
            task, mission, memory_context, previous_outputs or []
        )
        tier_b_budget = min(TOKEN_BUDGET_TIER_B, remaining_budget)
        used_b = 0
        for section in tier_b_sections:
            if used_b + section.token_estimate <= tier_b_budget:
                ctx.sections.append(section)
                ctx.total_tokens += section.token_estimate
                used_b += section.token_estimate
                remaining_budget -= section.token_estimate
            else:
                # Try trimming the section to fit
                trimmed = self._trim_to_budget(
                    section.content,
                    tier_b_budget - used_b
                )
                if trimmed:
                    trimmed_section = ContextSection.from_content(
                        f"{section.name} (trimmed)", trimmed, "B"
                    )
                    ctx.sections.append(trimmed_section)
                    ctx.total_tokens += trimmed_section.token_estimate
                    used_b += trimmed_section.token_estimate
                    remaining_budget -= trimmed_section.token_estimate
                ctx.truncated_sections.append(section.name)

        # ── TIER C: Full file content (on demand) ─────────────────────────────
        if remaining_budget > 500:  # Only if meaningful budget left
            tier_c_sections = self._build_tier_c(task, remaining_budget)
            for section in tier_c_sections:
                if remaining_budget - section.token_estimate > 200:
                    ctx.sections.append(section)
                    ctx.total_tokens += section.token_estimate
                    remaining_budget -= section.token_estimate
                else:
                    trimmed = self._trim_to_budget(section.content, remaining_budget - 200)
                    if trimmed:
                        trimmed_section = ContextSection.from_content(
                            f"{section.name} (trimmed)", trimmed, "C"
                        )
                        ctx.sections.append(trimmed_section)
                        ctx.total_tokens += trimmed_section.token_estimate
                        remaining_budget -= trimmed_section.token_estimate
                    ctx.truncated_sections.append(section.name)

        # ── Error context (always last, highest priority) ──────────────────────
        if error_context:
            error_section = ContextSection.from_content(
                "PREVIOUS FAILURE — REPAIR CONTEXT",
                (
                    f"Your previous attempt FAILED with this error:\n"
                    f"{error_context[:800]}\n\n"
                    f"Analyze this error carefully. Do NOT repeat the same approach."
                ),
                "A"
            )
            ctx.sections.insert(0, error_section)
            ctx.total_tokens += error_section.token_estimate

        ctx.budget_used_pct = (ctx.total_tokens / TOKEN_BUDGET_TOTAL) * 100
        logger.debug(ctx.summary())

        return ctx

    # ── Tier A builders ───────────────────────────────────────────────────────

    def _build_tier_a(
        self,
        task: MissionTask,
        mission: Mission,
    ) -> list[ContextSection]:
        """
        Build Tier A — always-present context sections.
        Fixed overhead, always injected.
        """
        sections: list[ContextSection] = []

        # 1. Task description
        sections.append(ContextSection.from_content(
            "CURRENT TASK",
            f"Title: {task.title}\n"
            f"Description: {task.description}\n"
            f"Success criterion: {task.acceptance_criteria}",
            "A"
        ))

        # 2. Mission progress summary
        completed_titles = [
            t.title for t in mission.tasks
            if t.state.value == "COMPLETED"
        ]
        if completed_titles:
            sections.append(ContextSection.from_content(
                "ALREADY COMPLETED",
                "\n".join(f"✓ {t}" for t in completed_titles[-5:]),
                "A"
            ))

        # 3. Workspace skeleton
        if self.workspace.is_locked:
            skeleton = self.workspace.get_skeleton()
            if skeleton:
                framework_str = self.workspace.index.framework_detected if (self.workspace.index and self.workspace.index.framework_detected) else 'unknown'
                sections.append(ContextSection.from_content(
                    f"WORKSPACE: {self.workspace.workspace_root.name} [{framework_str}]",
                    skeleton,
                    "A"
                ))

        return sections

    # ── Tier B builders ───────────────────────────────────────────────────────

    def _build_tier_b(
        self,
        task: MissionTask,
        mission: Mission,
        memory_context: str,
        previous_outputs: list[str],
    ) -> list[ContextSection]:
        sections: list[ContextSection] = []

        # ── 1. Skill detection and loading (per-task) ──────────────────────
        skill_content, loaded_skill_ids = self._load_skill_for_task(task)
        if skill_content:
            sections.append(ContextSection.from_content(
                f"ACTIVE SKILL: {', '.join(loaded_skill_ids)}",
                skill_content,
                "B"
            ))
            # Store loaded skill IDs on the task so MissionRunner can
            # include them in progress events
            task.skill_hint = loaded_skill_ids[0] if loaded_skill_ids else ""
            task._loaded_skill_ids = loaded_skill_ids  # runtime attr

        # ── 2. Memory context ──────────────────────────────────────────────
        if memory_context and memory_context.strip():
            sections.append(ContextSection.from_content(
                "PROJECT MEMORY",
                self._compress_memory(memory_context),
                "B"
            ))

        # ── 3. File signatures for relevant files ─────────────────────────
        if self.workspace.is_locked:
            relevant_files = self.workspace.get_relevant_files(
                task.description, max_files=4
            )
            sig_lines: list[str] = []
            for rel_path in relevant_files:
                if rel_path.endswith(".py"):
                    sigs = self.workspace.get_signatures(rel_path)
                    if sigs:
                        sig_lines.append(f"FILE: {rel_path}")
                        sig_lines.append(sigs)
                        sig_lines.append("")
            if sig_lines:
                sections.append(ContextSection.from_content(
                    "RELEVANT FILE SIGNATURES",
                    "\n".join(sig_lines),
                    "B"
                ))

        # ── 4. Recent tool outputs (continuity) ───────────────────────────
        if previous_outputs:
            recent = previous_outputs[-2:]
            combined = "\n\n".join(
                f"Previous output:\n{out[:400]}" for out in recent
            )
            sections.append(ContextSection.from_content(
                "RECENT OUTPUTS", combined, "B"
            ))

        # ── 5. Retry context ───────────────────────────────────────────────
        if task.retry_count > 0 and task.error_message:
            sections.append(ContextSection.from_content(
                f"RETRY {task.retry_count}/{task.max_retries}",
                f"Previous error: {task.error_message[:300]}\n"
                f"Use a different approach.",
                "B"
            ))

        return sections

    def _load_skill_for_task(
        self,
        task: MissionTask,
    ) -> tuple[str, list[str]]:
        """
        Run the intent classifier on the task description + title.
        Load and return the matching SKILL.md content and skill IDs.

        Returns (skill_content: str, skill_ids: list[str])
        """
        try:
            from core.intent_classifier import IntentClassifier

            # Use combined task text for better matching
            task_text = f"{task.title} {task.description}"

            # If the task already has a forced skill hint from the planner,
            # use that first (planner-assigned skill takes priority)
            if task.skill_hint:
                # Still run classifier to potentially add more skills
                forced = [task.skill_hint]
            else:
                forced = []

            classifier = IntentClassifier("skills/")
            detected = classifier.classify(task_text)

            # Merge forced and detected, deduplicate, cap at 2
            skill_ids = list(dict.fromkeys(forced + detected))[:2]

            if not skill_ids:
                return "", []

            # Load skill content
            skill_content, loaded_ids = classifier.build_skill_prompt_section(skill_ids)
            return skill_content, loaded_ids

        except Exception as e:
            from loguru import logger
            logger.warning(f"ContextBuilder._load_skill_for_task: {e}")
            return "", []

    # ── Tier C builders ───────────────────────────────────────────────────────

    def _build_tier_c(
        self,
        task: MissionTask,
        remaining_budget: int,
    ) -> list[ContextSection]:
        """
        Build Tier C — full file content, injected only when budget allows.
        Used for read_file tasks and code modification tasks.
        """
        if not self.workspace.is_locked:
            return []

        sections: list[ContextSection] = []
        task_lower = task.description.lower()

        # Only read files if the task explicitly requires it
        read_signals = ["read", "modify", "update", "fix", "debug", "refactor", "look at"]
        if not any(signal in task_lower for signal in read_signals):
            return []

        relevant_files = self.workspace.get_relevant_files(
            task.description, max_files=2
        )

        for rel_path in relevant_files:
            content = self.workspace.get_file_content(rel_path)
            if content and not content.startswith("ERROR"):
                sections.append(ContextSection.from_content(
                    f"FILE CONTENT: {rel_path}",
                    content,
                    "C"
                ))

        return sections

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _compress_memory(self, memory_context: str) -> str:
        """
        Compress memory context by taking only the most recent and important facts.
        Memory can grow very large — we take top 8 facts only.
        """
        lines = [l for l in memory_context.split("\n") if l.strip()]
        fact_lines = [
            l for l in lines
            if any(l.startswith(f"[{t}]") for t in
                   ["FACT", "BUG", "TASK_DONE", "BLOCKED", "DETAIL"])
        ]
        # Take most recent 8 facts
        selected = fact_lines[-8:]
        return "\n".join(selected)

    def _trim_to_budget(self, content: str, token_budget: int) -> str:
        """
        Trim content to fit within a token budget.
        Trims from the bottom (keeps most important content at top).
        """
        if token_budget <= 0:
            return ""
        char_budget = int(token_budget * CHARS_PER_TOKEN)
        if len(content) <= char_budget:
            return content
        trimmed = content[:char_budget]
        # Try to trim at a newline boundary
        last_newline = trimmed.rfind("\n")
        if last_newline > char_budget * 0.8:
            trimmed = trimmed[:last_newline]
        return trimmed + "\n... [CONTEXT TRIMMED TO FIT BUDGET]"

    def estimate_task_context_size(self, task: MissionTask) -> dict:
        """
        Estimate context size for a task before building it.
        Used for pre-flight checks.
        """
        relevant_files = self.workspace.get_relevant_files(task.description) \
            if self.workspace.is_locked else []
        skeleton_size = estimate_tokens(self.workspace.get_skeleton()) \
            if self.workspace.is_locked else 0
        return {
            "skeleton_tokens": skeleton_size,
            "relevant_files": relevant_files,
            "estimated_total": skeleton_size + 500,  # rough estimate
            "within_budget": skeleton_size + 500 < TOKEN_BUDGET_TOTAL,
        }
