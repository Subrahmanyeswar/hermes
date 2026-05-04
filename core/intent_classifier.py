# core/intent_classifier.py
# The HERMES Skill Engine intent classifier.
# Pure Python - no LLM, no ML model, no embeddings.
# Uses word-boundary regex with negation window detection.
# Requires minimum 2 distinct trigger keyword matches before loading any skill.
# Returns empty list if no skill reaches threshold - this is by design.
# Runs in < 5ms on any modern CPU.

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

NEGATION_WINDOW: int = 5
NEGATION_WORDS: frozenset[str] = frozenset(
    {
        "no",
        "not",
        "dont",
        "without",
        "don't",
        "avoid",
        "skip",
        "exclude",
        "except",
        "never",
        "instead",
        "rather",
    }
)
MIN_MATCHES: int = 2
MAX_SKILLS_PER_PROMPT: int = 2


@dataclass
class SkillMeta:
    """Metadata parsed from a SKILL.md YAML front matter block."""

    skill_id: str
    name: str
    description: str
    triggers: list[str]
    priority: int = 1
    max_tokens: int = 350


class IntentClassifier:
    """Classify user prompts into conservative HERMES skill selections."""

    def __init__(self, skills_dir: str = "skills/"):
        """Load skill metadata from each SKILL.md file in the skills directory."""
        self.skills_dir = Path(skills_dir)
        self.skills: list[SkillMeta] = []

        if not self.skills_dir.exists():
            logger.warning("Skills directory does not exist: {}", self.skills_dir)
            return

        for skill_dir in sorted(self.skills_dir.iterdir(), key=lambda path: path.name):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                content = skill_file.read_text(encoding="utf-8")
                data = self._parse_frontmatter(content)
                skill = SkillMeta(
                    skill_id=skill_dir.name,
                    name=str(data.get("name", skill_dir.name)),
                    description=str(data.get("description", "")),
                    triggers=[
                        str(trigger).lower()
                        for trigger in data.get("triggers", [])
                        if str(trigger).strip()
                    ],
                    priority=int(data.get("priority", 1)),
                    max_tokens=int(data.get("max_tokens", 350)),
                )
                self.skills.append(skill)
                logger.debug(
                    "Loaded skill | id={} | triggers={} | priority={}",
                    skill.skill_id,
                    len(skill.triggers),
                    skill.priority,
                )
            except (OSError, UnicodeError, ValueError) as exc:
                logger.warning("Failed to load skill {}: {}", skill_file, exc)

        logger.info("IntentClassifier loaded {} skill(s)", len(self.skills))

    def _parse_frontmatter(self, content: str) -> dict:
        """Parse YAML frontmatter manually. Handles: str, int, and list[str] values."""
        lines = content.split("\n")
        in_frontmatter = False
        result = {}
        for line in lines:
            stripped = line.strip()
            if stripped == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                    continue
                else:
                    break
            if not in_frontmatter:
                continue
            if ":" not in stripped:
                continue
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                items = value[1:-1].split(",")
                result[key] = [
                    item.strip().strip('"\'') for item in items if item.strip()
                ]
            elif value.isdigit():
                result[key] = int(value)
            else:
                result[key] = value.strip('"\'')
        return result

    def _word_matches(self, trigger: str, words: list[str]) -> bool:
        """Return True if trigger matches in the word list without preceding negation."""
        trigger_words = trigger.split()
        tlen = len(trigger_words)
        pattern = re.compile(r"\b" + re.escape(trigger) + r"\b")

        for i, word in enumerate(words):
            # Build the candidate span for single-word and multi-word triggers
            span = " ".join(words[i : i + tlen])
            if not pattern.search(span):
                continue
            # Negation window: up to NEGATION_WINDOW words before the match start
            window = words[max(0, i - NEGATION_WINDOW) : i]
            if any(w in NEGATION_WORDS for w in window):
                continue
            return True
        return False

    def classify(self, prompt: str) -> list[str]:
        """Return up to two matching skill IDs for a user prompt."""
        start = time.monotonic()
        # Use only the raw word list — negation windows are positionally correct
        words = prompt.lower().split()

        scored: list[tuple[SkillMeta, int]] = []
        for skill in self.skills:
            count = sum(
                1
                for trigger in set(skill.triggers)
                if self._word_matches(trigger.lower(), words)
            )
            if count >= MIN_MATCHES:
                scored.append((skill, count))

        scored.sort(key=lambda item: (item[1], item[0].priority), reverse=True)
        selected = [
            skill.skill_id for skill, _ in scored[:MAX_SKILLS_PER_PROMPT]
        ]
        elapsed = time.monotonic() - start
        logger.debug(
            "Intent classification | elapsed={:.4f}s | matches={} | selected={}",
            elapsed,
            len(scored),
            selected,
        )
        return selected

    def load_skill_content(self, skill_id: str) -> Optional[str]:
        """Return full SKILL.md content for a skill ID, or None if missing."""
        skill_file = self.skills_dir / skill_id / "SKILL.md"
        if not skill_file.exists():
            logger.debug("Skill content missing | id={}", skill_id)
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")
            logger.debug("Loaded skill content | id={} | chars={}", skill_id, len(content))
            return content
        except (OSError, UnicodeError) as exc:
            logger.warning("Failed to read skill content {}: {}", skill_file, exc)
            return None

    def build_skill_prompt_section(self, skill_ids: list[str]) -> tuple[str, list[str]]:
        """Load and combine skill contents for Tier 1 prompt injection."""
        contents: list[str] = []
        loaded_ids: list[str] = []

        for skill_id in skill_ids:
            content = self.load_skill_content(skill_id)
            if content is None:
                logger.warning("Skipping missing skill content | id={}", skill_id)
                continue
            contents.append(content)
            loaded_ids.append(skill_id)

        if not contents:
            return "", []
        if len(contents) == 1:
            return contents[0], loaded_ids

        return "\n\n--- SKILL SEPARATOR ---\n\n".join(contents), loaded_ids
