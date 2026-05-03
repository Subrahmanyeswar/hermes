# core/intent_classifier.py
# Intent classifier for the HERMES Skill Engine.
# Uses word-boundary regex with negation detection.
# Returns a list of skill IDs to load for a given user prompt.
# Never uses an LLM - pure Python, runs in microseconds.

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

NEGATION_WINDOW: int = 5
NEGATION_WORDS: frozenset[str] = frozenset(
    {"no", "not", "without", "don't", "avoid", "skip", "exclude"}
)
MIN_MATCHES: int = 2
MAX_SKILLS: int = 2


@dataclass
class SkillMeta:
    """Metadata describing a skill that can be loaded into Tier 1 context."""

    skill_id: str
    name: str
    description: str
    triggers: list[str]
    priority: int = 1


class IntentClassifier:
    """Classify user prompts into matching HERMES skill IDs."""

    def __init__(self, skills_dir: str = "skills/") -> None:
        """Scan the skills directory and load metadata from each SKILL.md file."""
        self.skills_dir: Path = Path(skills_dir)
        self.skills: list[SkillMeta] = []

        if not self.skills_dir.exists():
            logger.warning("Skills directory does not exist: {}", self.skills_dir)
            return

        for skill_dir in sorted(self.skills_dir.iterdir(), key=lambda path: path.name):
            if not skill_dir.is_dir():
                continue

            skill_file: Path = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                content: str = skill_file.read_text(encoding="utf-8")
                front_matter: dict[str, object] = self._parse_front_matter(content)
                self.skills.append(
                    SkillMeta(
                        skill_id=skill_dir.name,
                        name=str(front_matter.get("name", "")),
                        description=str(front_matter.get("description", "")),
                        triggers=[
                            str(trigger).lower()
                            for trigger in front_matter.get("triggers", [])
                            if str(trigger).strip()
                        ],
                        priority=int(front_matter.get("priority", 1)),
                    )
                )
            except (OSError, UnicodeError, ValueError) as exc:
                logger.warning("Failed to load skill metadata from {}: {}", skill_file, exc)

        logger.info("Loaded {} skills", len(self.skills))

    def _parse_front_matter(self, content: str) -> dict[str, object]:
        """Parse YAML-like front matter from a SKILL.md file."""
        match: re.Match[str] | None = re.match(
            r"\A---\s*\n(.*?)\n---",
            content,
            flags=re.DOTALL,
        )
        if match is None:
            return {}

        metadata: dict[str, object] = {}
        lines: list[str] = match.group(1).splitlines()
        index: int = 0

        while index < len(lines):
            line: str = lines[index].strip()
            index += 1
            if not line or line.startswith("#") or ":" not in line:
                continue

            key, raw_value = line.split(":", 1)
            key = key.strip()
            raw_value = raw_value.strip()

            if key == "triggers":
                if raw_value:
                    metadata[key] = self._parse_list_value(raw_value)
                else:
                    trigger_values: list[str] = []
                    while index < len(lines):
                        item_line: str = lines[index].strip()
                        if not item_line:
                            index += 1
                            continue
                        if not item_line.startswith("-"):
                            break
                        trigger_values.append(self._strip_quotes(item_line[1:].strip()))
                        index += 1
                    metadata[key] = trigger_values
                continue

            if key == "priority":
                metadata[key] = int(self._strip_quotes(raw_value or "1"))
                continue

            metadata[key] = self._strip_quotes(raw_value)

        return metadata

    def _parse_list_value(self, raw_value: str) -> list[str]:
        """Parse a simple inline YAML list value."""
        value: str = raw_value.strip()
        if not value.startswith("[") or not value.endswith("]"):
            return [self._strip_quotes(value)]

        inner_value: str = value[1:-1].strip()
        if not inner_value:
            return []

        return [
            self._strip_quotes(item.strip())
            for item in inner_value.split(",")
            if item.strip()
        ]

    def _strip_quotes(self, value: str) -> str:
        """Remove matching single or double quotes from a scalar value."""
        stripped_value: str = value.strip()
        if (
            len(stripped_value) >= 2
            and stripped_value[0] == stripped_value[-1]
            and stripped_value[0] in {"'", '"'}
        ):
            return stripped_value[1:-1]
        return stripped_value

    def _word_matches(self, trigger: str, tokens: list[str]) -> bool:
        """Return True when a trigger appears without nearby preceding negation."""
        pattern: re.Pattern[str] = re.compile(r"\b" + re.escape(trigger) + r"\b")

        for index, token in enumerate(tokens):
            if pattern.search(token) is None:
                continue

            negation_start: int = max(0, index - NEGATION_WINDOW)
            if any(word in NEGATION_WORDS for word in tokens[negation_start:index]):
                continue

            return True

        if " " in trigger:
            return self._phrase_words_match(trigger, tokens)

        return False

    def _phrase_words_match(self, trigger: str, tokens: list[str]) -> bool:
        """Return True when trigger words appear in order without negation."""
        trigger_words: list[str] = trigger.split()
        search_start: int = 0

        for trigger_word in trigger_words:
            pattern: re.Pattern[str] = re.compile(
                r"\b" + re.escape(trigger_word) + r"\b"
            )
            matched_index: int | None = None

            for index in range(search_start, len(tokens)):
                if " " in tokens[index] or pattern.search(tokens[index]) is None:
                    continue

                negation_start: int = max(0, index - NEGATION_WINDOW)
                if any(word in NEGATION_WORDS for word in tokens[negation_start:index]):
                    continue

                matched_index = index
                break

            if matched_index is None:
                return False

            search_start = matched_index + 1

        return True

    def classify(self, prompt: str) -> list[str]:
        """Return the top matching skill IDs for a user prompt."""
        word_tokens: list[str] = re.findall(r"[\w']+", prompt.lower())
        tokens: list[str] = []
        for index, token in enumerate(word_tokens):
            tokens.append(token)
            if index + 1 < len(word_tokens):
                tokens.append(" ".join(word_tokens[index : index + 2]))

        scored_skills: list[tuple[SkillMeta, int]] = []
        for skill in self.skills:
            match_count: int = sum(
                1
                for trigger in set(skill.triggers)
                if self._word_matches(trigger.lower(), tokens)
            )
            if match_count >= MIN_MATCHES:
                scored_skills.append((skill, match_count))

        scored_skills.sort(
            key=lambda item: (item[1], item[0].priority),
            reverse=True,
        )
        return [skill.skill_id for skill, _ in scored_skills[:MAX_SKILLS]]

    def load_skill_content(self, skill_id: str) -> str | None:
        """Return the full SKILL.md content for a skill ID if it exists."""
        skill_file: Path = self.skills_dir / skill_id / "SKILL.md"
        try:
            if not skill_file.exists():
                return None
            return skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            logger.warning("Failed to load skill content from {}: {}", skill_file, exc)
            return None

    def build_skill_prompt_section(self, skill_ids: list[str]) -> str:
        """Build the skill prompt section for the provided skill IDs."""
        if not skill_ids:
            return ""

        skill_contents: list[str] = []
        for skill_id in skill_ids:
            content: str | None = self.load_skill_content(skill_id)
            if content is not None:
                skill_contents.append(content)

        return "\n\n---SKILL SEPARATOR---\n\n".join(skill_contents)
