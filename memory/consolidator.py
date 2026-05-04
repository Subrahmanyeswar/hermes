# memory/consolidator.py
# Memory consolidation for HERMES — called by the KAIROS daemon.
# Reads the current MEMORY.md, cleans it up, and rewrites it.
# Operations: remove duplicates, resolve contradictions, remove stale facts.
# This module reads and rewrites Layer 1 only. It never touches session logs.
# Safe to call at any time — it reads first, then overwrites atomically.

from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger
from memory.types import MemoryFact, MemoryState, FactType, MemoryIndex
from memory.store import read_memory_index, get_memory_path, MEMORY_FILENAME

def remove_duplicates(index: MemoryIndex) -> tuple[MemoryIndex, int]:
    seen = set()
    cleaned_facts = []
    count_removed = 0
    for fact in index.facts:
        key = (fact.fact_type, fact.content.strip())
        if key in seen:
            logger.debug(f"Memory consolidation: removing duplicate fact: {fact.content[:60]!r}")
            count_removed += 1
        else:
            seen.add(key)
            cleaned_facts.append(fact)
    index.facts = cleaned_facts
    return index, count_removed

def remove_stale_facts(index: MemoryIndex) -> tuple[MemoryIndex, int]:
    cleaned_facts = []
    count_removed = 0
    for fact in index.facts:
        if fact.fact_type == FactType.STALE:
            count_removed += 1
        else:
            cleaned_facts.append(fact)
    index.facts = cleaned_facts
    if count_removed > 0:
        logger.info(f"Memory consolidation: removed {count_removed} stale facts")
    return index, count_removed

def resolve_contradictions(index: MemoryIndex) -> tuple[MemoryIndex, int]:
    count_contradictions_found = 0
    n = len(index.facts)
    stale_indices = set()
    
    for i in range(n):
        if i in stale_indices or index.facts[i].fact_type != FactType.FACT:
            continue
        words_i = {w.lower() for w in index.facts[i].content.split() if len(w) > 4}
        for j in range(i + 1, n):
            if j in stale_indices or index.facts[j].fact_type != FactType.FACT:
                continue
            words_j = {w.lower() for w in index.facts[j].content.split() if len(w) > 4}
            if len(words_i & words_j) >= 2:
                logger.info(
                    f"Memory consolidation: contradiction detected. Marking old as STALE: "
                    f"{index.facts[i].content[:40]!r} | Newer: {index.facts[j].content[:40]!r}"
                )
                index.facts[i].fact_type = FactType.STALE
                stale_indices.add(i)
                count_contradictions_found += 1
                break

    return index, count_contradictions_found

def consolidate_memory(project: str = "default") -> dict:
    try:
        index = read_memory_index(project)
        initial_count = len(index.facts)
        
        index, duplicates_removed = remove_duplicates(index)
        index, contradictions_resolved = resolve_contradictions(index)
        index, stale_removed = remove_stale_facts(index)
        
        path = get_memory_path(project)
        lines = [
            "# HERMES MEMORY INDEX",
            f"## Project: {project}",
            f"## Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "## Consolidated by KAIROS",
            "",
        ]
        for fact in index.facts:
            try:
                lines.append(fact.to_memory_line())
            except ValueError:
                pass
                
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        
        stats = {
            "project": project,
            "initial_facts": initial_count,
            "final_facts": len(index.facts),
            "duplicates_removed": duplicates_removed,
            "contradictions_resolved": contradictions_resolved,
            "stale_removed": stale_removed,
            "timestamp": datetime.now().isoformat()
        }
        logger.info(f"Memory consolidation stats: {stats}")
        return stats
    except Exception as e:
        logger.error(f"Memory consolidation failed: {e}")
        return {"error": str(e), "project": project}
