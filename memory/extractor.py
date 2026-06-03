# memory/extractor.py
# Memory extraction for HERMES — the "autoDream" logic.
# After every completed task, extract_memories() makes a structured Tier 1 call
# to produce a JSON list of facts to remember.
# CRITICAL: extracted facts start as PROPOSED. They become CONFIRMED only when
#           the caller provides proof of tool success (exit_code=0).
#           extract_memories() never writes to MEMORY.md directly.
#           The caller (orchestrator) handles confirmation and writing.

import json
import re
from typing import Optional
from loguru import logger
from memory.types import MemoryFact, MemoryState, FactType

EXTRACTION_SYSTEM_PROMPT = """You are a memory extraction agent for HERMES.
Your job is to read a task conversation and extract facts worth remembering.

You must respond with ONLY a valid JSON array. No explanation, no markdown, no text before or after.
Your entire response must be parseable by json.loads().

Extract only facts that are:
- Specific and verifiable (not vague opinions)
- About the project being built (framework, database, structure, bugs found)
- Worth knowing in a future session (persistent project decisions)

Do NOT extract:
- Things the user said that were questions or requests
- Temporary debugging steps that were reverted
- Generic programming advice
- TASK_DONE facts for actions that were NOT actually executed in the tool results. ONLY extract TASK_DONE for actions that the tool results prove were completed. Do not assume the entire user task was completed if the tools only performed a subset of the work.

Output format — a JSON array of objects:
[
  {
    "type": "FACT",
    "content": "Short, specific fact under 150 characters"
  },
  {
    "type": "TASK_DONE",
    "content": "What was completed and which tools were used"
  }
]

Valid types: FACT, BUG, TASK_DONE, BLOCKED, DETAIL
If nothing is worth remembering, return an empty array: []
Maximum 5 facts per extraction.
"""

async def extract_memories(task_description: str, conversation_history: list[dict], tool_results: list[dict], ollama_client, model: str = "qwen2.5-coder:7b") -> list[MemoryFact]:
    """Extract memory facts from a completed task. Returns list of PROPOSED facts — caller must confirm them after verifying tool success."""
    history_text = "\n".join([
        f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')[:200]}"
        for msg in conversation_history[-10:]  # last 10 messages only
    ])
    
    tool_results_text = "\n".join([
        f"Tool: {r.get('tool', 'unknown')} | Exit: {r.get('exit_code', '?')} | "
        f"Success: {r.get('success', False)}"
        for r in tool_results[-5:]  # last 5 tool results
    ])
    
    user_prompt = (
        f"Proposed task context: {task_description}\n\n"
        f"Conversation:\n{history_text}\n\n"
        f"Tool results:\n{tool_results_text}\n\n"
        f"Based ONLY on the actual tool results and what was successfully executed in the conversation, extract the facts worth remembering."
    )
    
    try:
        response = await ollama_client.generate(
            model=model,
            prompt=user_prompt,
            system=EXTRACTION_SYSTEM_PROMPT,
            keep_alive=0
        )
    except Exception as e:
        logger.error(f"Memory extraction failed — Ollama call error: {e}")
        return []

    def parse_extraction_response(response: str) -> list[dict]:
        cleaned = response.strip()
        # Strip markdown fences if model added them
        cleaned = re.sub(r'^```json\s*', '', cleaned)
        cleaned = re.sub(r'^```\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        cleaned = cleaned.strip()
        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, list):
                logger.warning(f"Memory extraction: expected JSON array, got {type(parsed)}")
                return []
            return parsed
        except json.JSONDecodeError as e:
            logger.warning(f"Memory extraction: JSON parse failed: {e} | response={response[:100]!r}")
            return []

    facts = []
    raw_facts = parse_extraction_response(response)
    
    for item in raw_facts[:5]:  # enforce maximum 5 facts
        if not isinstance(item, dict):
            continue
        
        fact_type_str = item.get("type", "FACT").upper()
        content = item.get("content", "").strip()
        
        if not content:
            continue
        
        # Map type string to FactType enum
        try:
            fact_type = FactType[fact_type_str]
        except KeyError:
            logger.warning(f"Memory extraction: unknown fact type '{fact_type_str}', defaulting to FACT")
            fact_type = FactType.FACT
        
        # Truncate if too long
        if len(content) > 150:
            content = content[:147] + "..."
            logger.warning(f"Memory extraction: truncated fact to 150 chars: {content[:60]!r}")
        
        fact = MemoryFact(
            fact_type=fact_type,
            content=content,
            state=MemoryState.PROPOSED  # Always PROPOSED — never CONFIRMED here
        )
        facts.append(fact)
        logger.debug(f"Memory extraction: created PROPOSED fact [{fact_type.value}]: {content[:60]!r}")
    
    logger.info(f"Memory extraction: extracted {len(facts)} PROPOSED facts from task: {task_description[:60]!r}")
    return facts


def confirm_and_write_facts(facts: list[MemoryFact], tool_name: str, exit_code: int, project: str = "default") -> int:
    """Confirm and write a list of PROPOSED facts. Called by the orchestrator after a tool succeeds. Returns count of facts successfully written."""
    from memory.store import write_fact

    written = 0
    for fact in facts:
        if fact.state != MemoryState.PROPOSED:
            logger.warning(f"confirm_and_write_facts: skipping non-PROPOSED fact: {fact.state.value}")
            continue
        try:
            fact.confirm(tool_name=tool_name, exit_code=exit_code)
            success = write_fact(fact, project=project)
            if success:
                written += 1
        except ValueError as e:
            logger.error(f"confirm_and_write_facts: could not confirm fact: {e}")
        except Exception as e:
            logger.error(f"confirm_and_write_facts: unexpected error writing fact: {e}")
    logger.info(f"Memory: wrote {written}/{len(facts)} facts for project '{project}'")
    return written
