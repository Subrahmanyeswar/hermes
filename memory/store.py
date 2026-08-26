# memory/store.py
# Layer 1 and Layer 2 memory store for HERMES.
# Layer 1: reads and writes MEMORY.md files.
# Layer 2: reads and writes per-project topic files in data/memory/project/
# CRITICAL RULE: write_fact() can only be called after fact.state == CONFIRMED.
#                This is enforced with an assertion — not a suggestion.

import re
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger
from dataclasses import dataclass
from memory.types import MemoryFact, MemoryState, FactType, MemoryIndex


MEMORY_FILENAME = "MEMORY.md"
LAYER2_BASE_DIR = Path("data/memory")
MAX_CONTEXT_LINES = 30       # max lines of MEMORY.md to inject into Tier 1 prompt
LINE_CHAR_LIMIT = 150        # enforced max characters per memory line


@dataclass
class SimpleFact:
    """
    A single parsed fact line from MEMORY.md.
    Used by MemoryViewPane to render memory content.
    """
    raw_line: str
    fact_type: str = "FACT"  # FACT, BUG, TASK_DONE, BLOCKED, DETAIL, STALE

    def to_memory_line(self) -> str:
        return self.raw_line

    @classmethod
    def from_line(cls, line: str) -> Optional["SimpleFact"]:
        """Parse a line from MEMORY.md into a SimpleFact."""
        line = line.strip()
        if not line or line.startswith("#"):
            return cls(raw_line=line, fact_type="HEADER")
        for prefix in ["[FACT]", "[BUG]", "[TASK_DONE]", "[BLOCKED]", "[DETAIL]", "[STALE]"]:
            if line.startswith(prefix):
                fact_type = prefix.strip("[]:")
                return cls(raw_line=line, fact_type=fact_type)
        if line:
            return cls(raw_line=line, fact_type="RAW")
        return None

def get_memory_path(project: str = "default") -> Path:
    if project == "default":
        path = Path(MEMORY_FILENAME)
    else:
        path = LAYER2_BASE_DIR / project / MEMORY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_memory_index(project: str = "default") -> MemoryIndex:
    path = get_memory_path(project)
    if not path.exists():
        return MemoryIndex(project=project, facts=[], last_updated=None)
    
    lines = path.read_text(encoding='utf-8').splitlines()
    facts = []
    for line in lines:
        # Parse each line into a MemoryFact if possible; ignore headers/comments.
        mem_fact = MemoryFact.from_memory_line(line, project=project)
        if mem_fact is not None:
            facts.append(mem_fact)
    
    last_updated = datetime.fromtimestamp(path.stat().st_mtime)
    logger.debug(f"Memory: loaded {len(facts)} facts for project '{project}'")
    return MemoryIndex(project=project, facts=facts, last_updated=last_updated)


def write_fact(fact: MemoryFact, project: str = "default") -> bool:
    assert fact.state == MemoryState.CONFIRMED, (
        f"CRITICAL: write_fact() called with fact in state '{fact.state.value}'. "
        f"The memory state machine was bypassed. This is a bug. "
        f"Facts must be confirmed via fact.confirm(tool_name, exit_code=0) before writing."
    )
    
    try:
        path = get_memory_path(project)
        index = read_memory_index(project)
        
        contradicting = index.find_contradicting(fact.content, fact.fact_type)
        if contradicting is not None:
            logger.info(
                f"Memory: contradiction detected. "
                f"Archiving old fact: {contradicting.content[:60]!r}. "
                f"New fact: {fact.content[:60]!r}"
            )
            contradicting.fact_type = FactType.STALE
            
        for existing in index.facts:
            if existing.content.strip() == fact.content.strip() and existing.fact_type == fact.fact_type:
                logger.debug(f"Memory: skipping duplicate fact: {fact.content[:60]!r}")
                fact.persist()  # Still mark as persisted even though we skip the write
                return True
                
        if len(fact.content) > LINE_CHAR_LIMIT:
            logger.error(f"Memory: fact content too long ({len(fact.content)} chars, max {LINE_CHAR_LIMIT}): {fact.content[:80]!r}")
            return False
            
        fact.persist()
        index.facts.append(fact)
        
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# HERMES MEMORY INDEX",
            f"## Project: {project}",
            f"## Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"",
        ]
        for f in index.facts:
            try:
                lines.append(f.to_memory_line())
            except ValueError:
                logger.warning(f"Memory: skipping fact with invalid line format: {f.content[:40]!r}")
                
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        logger.info(f"Memory: wrote fact [{fact.fact_type.value}]: {fact.content[:60]!r} to {path}")
        return True
    except Exception as e:
        logger.error(f"Memory: unexpected error writing fact: {e}")
        return False


def read_context_for_prompt(project: str = "default") -> str:
    index = read_memory_index(project)
    if not index.facts:
        return ""
        
    relevant_facts = [f for f in index.facts if f.fact_type != FactType.STALE]
    relevant_facts = relevant_facts[-MAX_CONTEXT_LINES:]
    
    lines = ["## Project Memory", ""]
    for fact in relevant_facts:
        lines.append(fact.to_memory_line())
        
    context = '\n'.join(lines)
    logger.debug(f"Memory: injected {len(relevant_facts)} lines into context")
    return context


def archive_stale_fact(fact: MemoryFact, project: str = "default") -> None:
    index = read_memory_index(project)
    for existing in index.facts:
        if existing.content == fact.content and existing.fact_type == fact.fact_type:
            existing.fact_type = FactType.STALE
            
    path = get_memory_path(project)
    lines = [
        f"# HERMES MEMORY INDEX",
        f"## Project: {project}",
        f"## Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
    ]
    for f in index.facts:
        try:
            lines.append(f.to_memory_line())
        except ValueError:
            pass
            
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    logger.debug(f"Memory: archived stale fact {fact.content[:60]!r}")


def write_layer2_topic(project: str, topic_name: str, content: str) -> bool:
    try:
        path = LAYER2_BASE_DIR / project / f"{topic_name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        logger.info(f"Memory: wrote Layer 2 topic {topic_name} to {path}")
        return True
    except Exception as e:
        logger.error(f"Memory: error writing Layer 2 topic {topic_name}: {e}")
        return False


def read_layer2_topic(project: str, topic_name: str) -> Optional[str]:
    path = LAYER2_BASE_DIR / project / f"{topic_name}.md"
    if path.exists():
        return path.read_text(encoding='utf-8')
    return None


def search_layer3(
    query: str,
    project: str = "default",
    max_results: int = 20,
    session_dir: Optional[Path] = None,
) -> list[dict]:
    """
    Search Layer 3 session logs line-by-line for matches against a query string.
    Never loads entire JSONL files into memory.
    Returns a list of matching parsed JSON event dictionaries.
    """
    import json
    log_dir = session_dir or Path("data/sessions")
    if not log_dir.exists():
        return []

    results: list[dict] = []
    query_lower = query.lower()

    # Iterate through session log files sorted by modification time descending
    log_files = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for log_file in log_files:
        if len(results) >= max_results:
            break
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if len(results) >= max_results:
                        break
                    line_str = line.strip()
                    if not line_str or query_lower not in line_str.lower():
                        continue
                    try:
                        data = json.loads(line_str)
                        results.append(data)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Error reading session log {log_file}: {e}")
            continue

    return results
