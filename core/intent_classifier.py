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


class SkillMetaList(list):
    """List subclass that also supports dict-like key access for compatibility."""

    def keys(self) -> list[str]:
        return [s.skill_id for s in self]

    def items(self):
        return [(s.skill_id, {"triggers": s.triggers, "name": s.name, "description": s.description, "path": getattr(s, "path", "")}) for s in self]

    def values(self):
        return [{"triggers": s.triggers, "name": s.name, "description": s.description, "path": getattr(s, "path", "")} for s in self]

    def get(self, key: str, default=None):
        for s in self:
            if s.skill_id == key:
                return {"triggers": s.triggers, "name": s.name, "description": s.description, "path": getattr(s, "path", "")}
        return default

    def __getitem__(self, item):
        if isinstance(item, str):
            for s in self:
                if s.skill_id == item:
                    return {"triggers": s.triggers, "name": s.name, "description": s.description, "path": getattr(s, "path", "")}
            raise KeyError(item)
        return super().__getitem__(item)


class IntentClassifier:
    """Classify user prompts into conservative HERMES skill selections."""

    def __init__(self, skills_dir: str = "skills/"):
        """Load skill metadata from each SKILL.md file in the skills directory."""
        self.skills_dir = Path(skills_dir)
        self.skills = SkillMetaList()

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
                content = skill_file.read_text(encoding="utf-8", errors="replace")
                data = self._parse_frontmatter(content)
                triggers = [
                    str(trigger).lower()
                    for trigger in data.get("triggers", [])
                    if str(trigger).strip()
                ]
                if not triggers:
                    triggers = self._extract_triggers(content, skill_dir.name)

                skill = SkillMeta(
                    skill_id=skill_dir.name,
                    name=str(data.get("name", skill_dir.name)),
                    description=str(data.get("description", "")),
                    triggers=triggers,
                    priority=int(data.get("priority", 1)),
                    max_tokens=int(data.get("max_tokens", 350)),
                )
                skill.path = str(skill_file)
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

    def _extract_triggers(self, content: str, skill_id: str) -> list[str]:
        """Extract trigger keywords from SKILL.md frontmatter or generate defaults."""
        # Try YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                match = re.search(r'triggers:\s*\[([^\]]+)\]', frontmatter)
                if match:
                    raw = match.group(1)
                    return [
                        t.strip().strip('"\'').lower()
                        for t in raw.split(",")
                        if t.strip()
                    ]

        # Fallback: derive triggers from skill_id
        triggers = skill_id.replace("-", " ").replace("_", " ").split()
        # Add common aliases
        alias_map = {
            "flask": ["flask", "rest api", "api server", "backend", "fastapi"],
            "react": ["react", "jsx", "component", "frontend", "next.js", "hooks"],
            "pytest": ["pytest", "unit test", "test suite", "testing", "test cases"],
            "debugging": ["debug", "fix", "error", "traceback", "broken", "exception"],
            "git": ["git", "github", "push", "commit", "pull request", "branch"],
            "security": ["security", "vulnerability", "audit", "injection", "xss"],
            "database": ["database", "schema", "sqlite", "postgresql", "sql"],
            "refactoring": ["refactor", "clean", "improve", "restructure", "solid"],
            "bash": ["bash", "shell script", "linux", "terminal", "automation"],
            "react-frontend": ["react", "frontend", "component", "tailwind", "ui"],
            "auto-docs": ["docs", "documentation", "readme", "docstring"],
            "code-review": ["review", "check", "feedback", "code quality"],
            "screenshot-to-code": ["screenshot", "image", "mockup", "design to code"],
        }
        for key, aliases in alias_map.items():
            if key in skill_id:
                return [a.lower() for a in aliases]
        return [t.lower() for t in triggers]

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
        skill_file = Path(self.skills_dir) / skill_id / "SKILL.md"
        if not skill_file.exists():
            for candidate in [
                Path(self.skills_dir) / skill_id.replace("-", "_") / "SKILL.md",
                Path(self.skills_dir) / skill_id.replace("_", "-") / "SKILL.md",
            ]:
                if candidate.exists():
                    skill_file = candidate
                    break
            else:
                logger.debug("Skill content missing | id={}", skill_id)
                return None

        try:
            content = skill_file.read_text(encoding="utf-8", errors="replace")
            logger.debug("Loaded skill content | id={} | chars={}", skill_id, len(content))
            return content
        except (OSError, UnicodeError) as exc:
            logger.warning("Failed to read skill content {}: {}", skill_file, exc)
            return None

    def build_skill_prompt_section(
        self,
        skill_ids: list[str],
    ) -> tuple[str, list[str]]:
        """
        Load SKILL.md files for the given skill IDs and build a combined
        prompt section string.

        Returns (combined_content: str, successfully_loaded_ids: list[str])
        """
        loaded_ids: list[str] = []
        sections: list[str] = []

        skills_dir_path = Path(self.skills_dir)

        for skill_id in skill_ids[:2]:  # Max 2 skills
            skill_path = skills_dir_path / skill_id / "SKILL.md"

            if not skill_path.exists():
                # Try alternate path formats
                for candidate in [
                    skills_dir_path / skill_id.replace("-", "_") / "SKILL.md",
                    skills_dir_path / skill_id.replace("_", "-") / "SKILL.md",
                ]:
                    if candidate.exists():
                        skill_path = candidate
                        break
                else:
                    logger.debug(f"IntentClassifier: skill file not found: {skill_path}")
                    continue

            try:
                content = skill_path.read_text(encoding="utf-8", errors="replace")
                # Strip YAML frontmatter if present
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        content = parts[2].strip()
                sections.append(f"# Skill: {skill_id}\n{content}")
                loaded_ids.append(skill_id)
            except Exception as e:
                logger.warning(f"IntentClassifier: error loading {skill_path}: {e}")

        if not sections:
            return "", []

        combined = "\n\n--- SKILL SEPARATOR ---\n\n".join(sections)
        return combined, loaded_ids
